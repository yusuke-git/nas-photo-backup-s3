#!/usr/bin/env bash
# 2. ラズパイで NAS をマウントし、rclone のバックアップを設定して試運転する。
#   使い方: 下の「設定」を書き換えてから、普段のユーザー（pi など。root ではない）で
#     bash setup/2-pi-backup.sh
#   途中で sudo のパスワード、NAS のパスワード、AWS のアクセスキーを聞かれる（画面には表示しない）。
#   最後に試運転（DRY_RUN、ほぼ無料）の結果を出し、yes と入力したときだけ本番のアップロードとタイマーを始める。
#   もう一度実行しても、作成済みのファイルは上書きしない（やり直したいときはそのファイルを消してから実行）。
set -euo pipefail

# ===== 設定（ここを書き換える） =====
NAS_IP="<NASのIP>"                             # NAS の IP アドレス（例 192.168.1.20）
NAS_USER="nas-pi"                               # NAS に作ったラズパイ専用ユーザー
NAS_PHOTO_SHARE="Photo"                         # 写真の共有フォルダ名（ラズパイからは読み取り専用）
NAS_THUMB_SHARE="Thumbnail"                     # Immich のサムネイル用の共有フォルダ名（読み書き）
SMB_VERSION="2.0"                               # つながらなければ 1.0（古い方式なので LAN の中だけで使う）
BUCKET_NAME="example-nas-photo-backup-XXXX"     # 1-aws で作ったバケット名
REGION="ap-southeast-2"                         # バケットのリージョン
# ====================================

PHOTO_MNT=/mnt/nas/photos
THUMB_MNT=/mnt/nas/thumbnail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(id -un)"
RCLONE_CONF="$HOME/.config/rclone/rclone.conf"
DEST="s3backup:$BUCKET_NAME/photos"

die() { echo "エラー: $*" >&2; exit 1; }
step() { echo; echo "=== $* ==="; }

[ "$(id -u)" -ne 0 ] || die "root ではなく、普段のユーザーで実行してください（必要なところだけ sudo を使います）"
case "$NAS_IP$BUCKET_NAME" in
  *"<"*|*example*) die "スクリプト冒頭の設定（NAS_IP と BUCKET_NAME）を書き換えてから実行してください" ;;
esac

step "1/7 パッケージを入れる"
sudo apt-get update -qq
sudo apt-get install -y -qq cifs-utils rclone

step "2/7 NAS のパスワードを保存する（/etc/nas-credentials、権限 600）"
if sudo test -f /etc/nas-credentials; then
  echo "すでにあるのでそのまま使います"
else
  read -r -s -p "NAS のユーザー $NAS_USER のパスワード: " nas_pass; echo
  sudo install -m 600 /dev/null /etc/nas-credentials
  printf 'username=%s\npassword=%s\n' "$NAS_USER" "$nas_pass" | sudo tee /etc/nas-credentials >/dev/null
  unset nas_pass
fi

step "3/7 NAS をマウントする（$PHOTO_MNT は読み取り専用、$THUMB_MNT は読み書き）"
sudo mkdir -p "$PHOTO_MNT" "$THUMB_MNT"
opts="credentials=/etc/nas-credentials,vers=$SMB_VERSION,iocharset=utf8,uid=$RUN_USER,gid=$(id -gn),_netdev,nofail"
add_fstab() {  # $1=共有名 $2=マウント先 $3=追加オプション
  if grep -qE "[[:space:]]$2[[:space:]]" /etc/fstab; then
    echo "/etc/fstab に $2 の行がすでにあるのでそのまま使います"
  else
    printf '//%s/%s  %s  cifs  %s,%s  0  0\n' "$NAS_IP" "$1" "$2" "$opts" "$3" | sudo tee -a /etc/fstab >/dev/null
    echo "/etc/fstab に $2 を追加しました"
  fi
}
add_fstab "$NAS_PHOTO_SHARE" "$PHOTO_MNT" "ro"
add_fstab "$NAS_THUMB_SHARE" "$THUMB_MNT" "rw,file_mode=0644,dir_mode=0755"
sudo systemctl daemon-reload
sudo mount -a || true
mountpoint -q "$PHOTO_MNT" || die "$PHOTO_MNT をマウントできません。NAS_IP、共有名、パスワード、SMB_VERSION を確認してください（dmesg | tail で原因が出ます）"
mountpoint -q "$THUMB_MNT" || die "$THUMB_MNT をマウントできません"
touch "$THUMB_MNT/.write-test" && rm "$THUMB_MNT/.write-test" || die "$THUMB_MNT に書き込めません。NAS 側で $NAS_USER に読み書きを許可してください"
echo "NAS の写真フォルダ: $(ls "$PHOTO_MNT" | head -5 | tr '\n' ' ')"

step "4/7 rclone に AWS のアクセスキーを設定する（$RCLONE_CONF、権限 600）"
if [ -f "$RCLONE_CONF" ]; then
  echo "すでにあるのでそのまま使います"
else
  echo "AWS コンソールで IAM → ユーザー → nas-backup → セキュリティ認証情報 → アクセスキーを作成し、"
  echo "表示された2つの値を貼り付けてください（シークレットは再表示できないので、ここでだけ使います）。"
  read -r -p "アクセスキー ID: " key_id
  read -r -s -p "シークレットアクセスキー: " key_secret; echo
  mkdir -p "$(dirname "$RCLONE_CONF")"
  ( umask 077
    cat > "$RCLONE_CONF" <<EOF
[s3backup]
type = s3
provider = AWS
access_key_id = $key_id
secret_access_key = $key_secret
region = $REGION
location_constraint = $REGION
storage_class = DEEP_ARCHIVE
server_side_encryption = AES256
no_check_bucket = true
EOF
  )
  unset key_id key_secret
fi
rclone lsd "s3backup:$BUCKET_NAME" >/dev/null || die "S3 に接続できません。キーとバケット名を確認してください"
echo "S3 に接続できました"

step "5/7 バックアップの設定とログ"
sudo mkdir -p /etc/nas-backup /var/log/nas-backup
sudo chown "$RUN_USER:$(id -gn)" /var/log/nas-backup
if [ -f /etc/nas-backup/backup.env ]; then
  echo "/etc/nas-backup/backup.env はすでにあるのでそのまま使います"
else
  printf 'SRC=%s\nDEST=%s\nLOG_DIR=/var/log/nas-backup\nDRY_RUN=0\n' "$PHOTO_MNT" "$DEST" | sudo tee /etc/nas-backup/backup.env >/dev/null
fi
sudo cp "$REPO_DIR/backup/logrotate.conf" /etc/logrotate.d/nas-backup

step "6/7 試運転（DRY_RUN。一覧を取るだけで、アップロードはしない）"
: > /var/log/nas-backup/backup.log
DRY_RUN=1 "$REPO_DIR/backup/backup.sh"
count=$(grep -c "Skipped copy" /var/log/nas-backup/backup.log || true)
echo "アップロード予定: ${count} 件（拡張子ごと）"
grep "Skipped copy" /var/log/nas-backup/backup.log | sed 's/: Skipped copy.*//; s/.*\.//' | sort | uniq -c || true
echo "NAS にあるファイル（拡張子ごと、参考）"
find "$PHOTO_MNT" -type f -not -path '*/.*/*' | sed 's/.*\.//' | sort | uniq -c
echo "初回のリクエスト料金の目安: 約 $(awk "BEGIN{printf \"%.2f\", $count*0.06/1000}") ドル（1,000 件 0.06 ドル）"
echo "詳しくは /var/log/nas-backup/backup.log を見てください"

step "7/7 本番のアップロードと毎晩のタイマー"
echo "Deep Archive は180日以内に消しても課金されます。上の件数と拡張子が想定どおりか確認してください。"
read -r -p "本番のアップロードを始め、毎晩 02:00 のタイマーを有効にしますか？ (yes/no) " ans
if [ "$ans" != "yes" ]; then
  echo "本番は始めずに終了しました。始めるときは、もう一度このスクリプトを実行してください。"
  exit 0
fi
sed -e "s|^User=.*|User=$RUN_USER|" -e "s|^ExecStart=.*|ExecStart=$REPO_DIR/backup/backup.sh|" \
  "$REPO_DIR/backup/systemd/nas-backup.service" | sudo tee /etc/systemd/system/nas-backup.service >/dev/null
sudo cp "$REPO_DIR/backup/systemd/nas-backup.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start --no-block nas-backup.service
sudo systemctl enable --now nas-backup.timer
echo
echo "初回のアップロードをバックグラウンドで始めました（SSH を切っても止まりません）。"
echo "  進み具合: tail -f /var/log/nas-backup/backup.log"
echo "  状態:     systemctl status nas-backup.service"
echo "次は Immich を使う場合、setup/3-pi-immich.sh を実行します。"
