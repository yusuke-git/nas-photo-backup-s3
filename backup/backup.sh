#!/usr/bin/env bash
# NAS の写真を S3 Glacier Deep Archive に追加のみでコピーする。
# 削除・上書きは一切しない（180日以内の削除課金を避けるため）。
set -euo pipefail

CONF_FILE="${CONF_FILE:-/etc/nas-backup/backup.env}"
# コマンドラインで指定した DRY_RUN（例: DRY_RUN=1 backup.sh）を backup.env の値より優先する
ENV_DRY_RUN="${DRY_RUN:-}"
# shellcheck source=/dev/null
[ -f "$CONF_FILE" ] && . "$CONF_FILE"
[ -n "$ENV_DRY_RUN" ] && DRY_RUN="$ENV_DRY_RUN"

SRC="${SRC:-/mnt/nas/photos}"
DEST="${DEST:?DEST を backup.env に設定してください（例: s3backup:example-nas-photo-backup/photos）}"
LOG_DIR="${LOG_DIR:-/var/log/nas-backup}"
LOCK_FILE="${LOCK_FILE:-/run/lock/nas-backup.lock}"
DRY_RUN="${DRY_RUN:-0}"

mkdir -p "$LOG_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "別のバックアップが実行中のため終了します" >&2
  exit 0
fi

# NAS がマウントされていないと空ディレクトリをコピーしてしまうので確認する
if ! mountpoint -q "$SRC" && ! mountpoint -q "$(dirname "$SRC")"; then
  echo "NAS がマウントされていません: $SRC" >&2
  exit 1
fi

args=(
  copy "$SRC" "$DEST"
  --immutable          # 既存オブジェクトと違う場合は上書きせずエラーにする
  --size-only          # 更新日時の取得（HEAD リクエスト）を省いて料金を抑える
  --s3-no-head         # アップロード後の HEAD 確認を省く
  # 隠しフォルダ（Buffalo WebAccess の .webaxs/thumbnail など NAS が自動で作るサムネイル）は除外し、
  # 元写真の JPEG・RAW（CR2）・動画（MOV）だけを対象にする。ルールは上から順に評価される
  --filter "- .*/**"
  --filter "+ *.{jpg,jpeg,JPG,JPEG,cr2,CR2,mov,MOV}"
  --filter "- *"
  --transfers 2
  --log-file "$LOG_DIR/backup.log"
  --log-level INFO
  --stats-one-line --stats 0
)
[ "$DRY_RUN" = "1" ] && args+=(--dry-run)

rclone "${args[@]}"
