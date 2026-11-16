#!/usr/bin/env bash
# Immich（コンテナ）から、Windows PC / Mac の機械学習コンテナへの通信を中継する。
#   コンテナの中からは mDNS（xxx.local）の名前を引けないため、ラズパイ本体で名前を引いてつなぐ。
#   接続のたびに名前を引き直すので、PC の IP が DHCP で変わっても追従する。固定 IP は不要。
#
# 使い方: ml-relay.sh primary|backup   （systemd の immich-ml-relay@primary / @backup から呼ばれる）
#   primary: .env の ML_PRIMARY_HOST へ。Immich からは http://host.docker.internal:3101
#   backup : .env の ML_BACKUP_HOST  へ。Immich からは http://host.docker.internal:3102
# 名前には mDNS（desktop-abc123.local）、Tailscale の名前（windows-pc）、IP のどれでも書ける。
set -euo pipefail

ENV_FILE="${ENV_FILE:-$(cd "$(dirname "$0")/.." && pwd)/.env}"

case "${1:-}" in
  primary) var=ML_PRIMARY_HOST; port=3101 ;;
  backup)  var=ML_BACKUP_HOST;  port=3102 ;;
  *) echo "使い方: $0 primary|backup" >&2; exit 2 ;;
esac

[ -r "$ENV_FILE" ] || { echo "$ENV_FILE が読めません" >&2; exit 1; }
# .env の「名前=値」から値だけを取り出す（引用符と空白は取り除く）
host=$(sed -n "s/^${var}=//p" "$ENV_FILE" | tail -n 1 | tr -d "\"' \r")
if [ -z "$host" ]; then
  echo "$var が空なので中継しません"
  exit 0
fi

# Docker のブリッジ（docker0）の IP だけで待ち受ける。LAN からは見えない
bind=$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n 1)
[ -n "$bind" ] || { echo "docker0 が見つかりません（Docker が起動していない）" >&2; exit 1; }

echo "中継: $bind:$port -> $host:3003"
exec socat "TCP-LISTEN:$port,bind=$bind,fork,reuseaddr" "TCP:$host:3003,connect-timeout=3"
