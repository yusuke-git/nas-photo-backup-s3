#!/usr/bin/env bash
# 3. ラズパイで Immich を起動する（NAS の写真を外部ライブラリとして読み取り専用で取り込む）。
#   先に setup/2-pi-backup.sh で NAS をマウントしておくこと。
#   使い方: 下の「設定」を必要なら書き換えてから、普段のユーザーで  bash setup/3-pi-immich.sh
#   AWS には何もしない。
set -euo pipefail

# ===== 設定（必要なら書き換える） =====
DB_STORAGE_TYPE="SSD"          # DB を SSD に置くなら SSD、SD カードや HDD なら HDD
IMMICH_DATA="/srv/immich"      # Immich の DB・動画変換などの置き場所（ラズパイのローカルディスク。NAS は不可）
TIMEZONE="Asia/Tokyo"
# 顔認識などの機械学習を動かす PC の名前（docs/setup-remote-ml.md）。固定 IP は不要。空なら使わない
ML_PRIMARY_HOST=""             # 例: desktop-abc123.local（Windows のデバイス名 + .local）
ML_BACKUP_HOST=""              # 例: my-mac.local（Mac のローカルホスト名）。予備
# ======================================

PHOTO_MNT=/mnt/nas/photos
THUMB_MNT=/mnt/nas/thumbnail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMMICH_DIR="$REPO_DIR/immich"

die() { echo "エラー: $*" >&2; exit 1; }
step() { echo; echo "=== $* ==="; }

[ "$(id -u)" -ne 0 ] || die "root ではなく、普段のユーザーで実行してください"
[ "$(uname -m)" = "aarch64" ] || die "64bit の OS（uname -m が aarch64）が必要です"
mountpoint -q "$PHOTO_MNT" && mountpoint -q "$THUMB_MNT" || die "NAS がマウントされていません。先に setup/2-pi-backup.sh を実行してください"

step "1/5 Docker を入れる"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  echo "Docker と Compose はインストール済みです"
else
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$(id -un)"   # 次のログインから sudo なしで docker を使える

step "2/5 置き場所と .env"
sudo mkdir -p "$IMMICH_DATA/library" "$IMMICH_DATA/postgres"
if [ -f "$IMMICH_DIR/.env" ]; then
  echo ".env はすでにあるのでそのまま使います"
else
  ( umask 077
    sed -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$(openssl rand -hex 24)|" \
        -e "s|^DB_STORAGE_TYPE=.*|DB_STORAGE_TYPE=$DB_STORAGE_TYPE|" \
        -e "s|^UPLOAD_LOCATION=.*|UPLOAD_LOCATION=$IMMICH_DATA/library|" \
        -e "s|^DB_DATA_LOCATION=.*|DB_DATA_LOCATION=$IMMICH_DATA/postgres|" \
        -e "s|^TZ=.*|TZ=$TIMEZONE|" \
        "$IMMICH_DIR/example.env" > "$IMMICH_DIR/.env" )
  echo ".env を作りました（DB のパスワードはランダムに生成）"
fi
# 機械学習の PC の名前は、設定に書いたときだけ .env に反映する（既存の .env でも上書き）
for kv in "ML_PRIMARY_HOST=$ML_PRIMARY_HOST" "ML_BACKUP_HOST=$ML_BACKUP_HOST"; do
  key=${kv%%=*}; val=${kv#*=}
  [ -n "$val" ] || continue
  if grep -q "^$key=" "$IMMICH_DIR/.env"; then
    sed -i "s|^$key=.*|$key=$val|" "$IMMICH_DIR/.env"
  else
    echo "$key=$val" >> "$IMMICH_DIR/.env"
  fi
done

step "3/5 NAS のマウント後に Docker を起動するようにする"
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo cp "$IMMICH_DIR/systemd/docker.service.d/wait-nas.conf" /etc/systemd/system/docker.service.d/
sudo systemctl daemon-reload
sudo systemctl restart docker

step "4/5 機械学習の PC への中継（immich/ml-relay/）"
ml_primary=$(sed -n 's/^ML_PRIMARY_HOST=//p' "$IMMICH_DIR/.env" | tr -d "\"' ")
ml_backup=$(sed -n 's/^ML_BACKUP_HOST=//p' "$IMMICH_DIR/.env" | tr -d "\"' ")
if [ -z "$ml_primary$ml_backup" ]; then
  echo "ML_PRIMARY_HOST / ML_BACKUP_HOST が空なので省略します（顔認識などは動きません）"
else
  sudo apt-get install -y socat avahi-daemon libnss-mdns >/dev/null
  sed "s|@REPO_DIR@|$REPO_DIR|" "$IMMICH_DIR/ml-relay/immich-ml-relay@.service" \
    | sudo tee /etc/systemd/system/immich-ml-relay@.service >/dev/null
  sudo systemctl daemon-reload
  for pair in "primary:$ml_primary" "backup:$ml_backup"; do
    name=${pair%%:*}; host=${pair#*:}
    if [ -n "$host" ]; then
      sudo systemctl enable --now "immich-ml-relay@$name"
      sudo systemctl restart "immich-ml-relay@$name"
      if getent hosts "$host" >/dev/null; then
        echo "$name: $host を見つけました"
      else
        echo "$name: $host がいま見つかりません（PC の電源とネットワークを確認。起動していれば自動でつながります）"
      fi
    else
      sudo systemctl disable --now "immich-ml-relay@$name" 2>/dev/null || true
    fi
  done
fi

step "5/5 Immich を起動する（初回はイメージのダウンロードに数分かかる）"
cd "$IMMICH_DIR"
sudo docker compose up -d
sudo docker compose ps

ip=$(hostname -I | awk '{print $1}')
echo
echo "起動しました（server / redis / database の 3 つが動いていれば正常）。"
echo "  1. ブラウザで http://$ip:2283 を開いて管理者を作る"
echo "  2. 「管理」→「外部ライブラリ」→ ライブラリを作成し、フォルダに /mnt/media/photos を指定してスキャン"
echo "  3. 外から見るときは Tailscale を使う（ルーターのポートは開けない）。docs/setup-immich.md の 7 章"
