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

step "1/4 Docker を入れる"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  echo "Docker と Compose はインストール済みです"
else
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$(id -un)"   # 次のログインから sudo なしで docker を使える

step "2/4 置き場所と .env"
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

step "3/4 NAS のマウント後に Docker を起動するようにする"
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo cp "$IMMICH_DIR/systemd/docker.service.d/wait-nas.conf" /etc/systemd/system/docker.service.d/
sudo systemctl daemon-reload
sudo systemctl restart docker

step "4/4 Immich を起動する（初回はイメージのダウンロードに数分かかる）"
cd "$IMMICH_DIR"
sudo docker compose up -d
sudo docker compose ps

ip=$(hostname -I | awk '{print $1}')
echo
echo "起動しました（server / redis / database の 3 つが動いていれば正常）。"
echo "  1. ブラウザで http://$ip:2283 を開いて管理者を作る"
echo "  2. 「管理」→「外部ライブラリ」→ ライブラリを作成し、フォルダに /mnt/media/photos を指定してスキャン"
echo "  3. 外から見るときは Tailscale を使う（ルーターのポートは開けない）。docs/setup-immich.md の 7 章"
