#!/usr/bin/env bash
# 1. AWS 側（S3 バケット、IAM ユーザー、予算と自動停止）を Terraform で作る。Mac / Linux の PC で実行する。
#    Windows の場合は setup/1-aws.ps1 を使う。
#   使い方: 下の「設定」を書き換えてから  bash setup/1-aws.sh
#   必要なもの: AWS CLI v2（aws login が使える版）、Terraform 1.6 以上
#   terraform apply の前に plan の内容を表示し、yes と入力したときだけ作成する（作成時の費用は 0 円）。
#   state（terraform.tfstate）はこのリポジトリの infra に保存される。以後の変更もこのフォルダで行うこと。
set -euo pipefail

# ===== 設定（ここを書き換える） =====
BUCKET_NAME="example-nas-photo-backup-XXXX"   # 世界で一意のバケット名（小文字・数字・ハイフン）
BUDGET_EMAIL="you@example.com"                # 予算と異常検知の通知先
REGION="ap-southeast-2"                       # AWS のリージョン（新しい AWS エクスペリエンスはプロジェクトのリージョン）
AWS_PROFILE_NAME="nas-admin"                  # 管理者でサインインする AWS CLI のプロファイル名
MONTHLY_BUDGET_USD=5                          # 月の予算（USD）。超えるとアップロードを自動で止める
# ====================================

die() { echo "エラー: $*" >&2; exit 1; }

case "$BUCKET_NAME$BUDGET_EMAIL" in
  *example*) die "スクリプト冒頭の設定（BUCKET_NAME と BUDGET_EMAIL）を書き換えてから実行してください" ;;
esac
command -v aws >/dev/null || die "aws が見つかりません"
command -v terraform >/dev/null || die "terraform が見つかりません"

INFRA_DIR="$(cd "$(dirname "$0")/../infra" && pwd)"
cd "$INFRA_DIR"
echo "作業フォルダ: $INFRA_DIR"

write_tfvars() {
  cat > terraform.tfvars <<EOF
bucket_name        = "$BUCKET_NAME"
budget_email       = "$BUDGET_EMAIL"
region             = "$REGION"
monthly_budget_usd = $MONTHLY_BUDGET_USD
EOF
}
if [ -f terraform.tfvars ]; then
  read -r -p "terraform.tfvars がすでにあります。上の設定で書き換えますか？ (yes/no) " ans
  if [ "$ans" = "yes" ]; then write_tfvars; fi
else
  write_tfvars
fi

# サインイン（切れていればブラウザが開く）
if ! aws sts get-caller-identity --profile "$AWS_PROFILE_NAME" >/dev/null 2>&1; then
  aws login --region "$REGION" --profile "$AWS_PROFILE_NAME"
fi

# Terraform の AWS プロバイダ v5 は aws login の認証を直接読めないため、一時認証情報を環境変数で渡す
eval "$(aws configure export-credentials --profile "$AWS_PROFILE_NAME" --format env)"

terraform init -input=false
terraform plan -input=false -var "aws_profile=" -out=tfplan

echo
echo "上の plan の最後の行（Plan: X to add, Y to change, Z to destroy）を確認してください。"
echo "初回は 16 to add / 0 to change / 0 to destroy になります。destroy があれば止めてください。"
read -r -p "この内容で AWS に作成（terraform apply）しますか？ (yes/no) " ans
if [ "$ans" != "yes" ]; then
  echo "apply せずに終了しました。AWS には何も作っていません。"
  exit 0
fi
terraform apply -input=false tfplan

echo
echo "完了しました。次はラズパイで setup/2-pi-backup.sh を実行します。"
echo "  BUCKET_NAME には $BUCKET_NAME を書きます（rclone の保存先: $(terraform output -raw rclone_dest)）"
echo "  アクセスキーは、2-pi-backup.sh が聞いてきたときに AWS コンソールで発行します"
echo "  （IAM → ユーザー → nas-backup → セキュリティ認証情報 → アクセスキーを作成）"
