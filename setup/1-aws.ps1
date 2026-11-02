# 1. AWS 側（S3 バケット、IAM ユーザー、予算と自動停止）を Terraform で作る。手元の Windows PC で実行する。
#   使い方: 下の「設定」を書き換えてから、リポジトリのフォルダで
#     powershell -ExecutionPolicy Bypass -File setup\1-aws.ps1
#   必要なもの: AWS CLI v2（aws login が使える版）、Terraform 1.6 以上
#   terraform apply の前に plan の内容を表示し、yes と入力したときだけ作成する（作成時の費用は 0 円）。
#   state（terraform.tfstate）はこのリポジトリの infra に保存される。以後の変更もこのフォルダで行うこと。

# ===== 設定（ここを書き換える） =====
$BucketName       = "example-nas-photo-backup-XXXX"   # 世界で一意のバケット名（小文字・数字・ハイフン）
$BudgetEmail      = "you@example.com"                 # 予算と異常検知の通知先
$Region           = "ap-southeast-2"                  # AWS のリージョン（新しい AWS エクスペリエンスはプロジェクトのリージョン）
$AwsProfile       = "nas-admin"                       # 管理者でサインインする AWS CLI のプロファイル名
$MonthlyBudgetUsd = 5                                 # 月の予算（USD）。超えるとアップロードを自動で止める
# ====================================

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Message)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

if ($BucketName -match "example" -or $BudgetEmail -match "example\.com") {
    throw "スクリプト冒頭の設定（BucketName と BudgetEmail）を書き換えてから実行してください"
}
foreach ($cmd in "aws", "terraform") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd が見つかりません。インストールしてから実行してください" }
}

$InfraDir = (Resolve-Path (Join-Path $PSScriptRoot "..\infra")).Path
Set-Location $InfraDir
Write-Host "作業フォルダ: $InfraDir"

# terraform.tfvars（Git には入らない）
$tfvars = @"
bucket_name        = "$BucketName"
budget_email       = "$BudgetEmail"
region             = "$Region"
monthly_budget_usd = $MonthlyBudgetUsd
"@
function Write-Tfvars {
    # BOM なしの UTF-8 で書く（Windows PowerShell 5.1 の -Encoding UTF8 は BOM を付けるため）
    [System.IO.File]::WriteAllText((Join-Path $InfraDir "terraform.tfvars"), $tfvars, (New-Object System.Text.UTF8Encoding($false)))
}
if (Test-Path terraform.tfvars) {
    $ans = Read-Host "terraform.tfvars がすでにあります。上の設定で書き換えますか？ (yes/no)"
    if ($ans -eq "yes") { Write-Tfvars }
} else {
    Write-Tfvars
}

# サインイン（切れていればブラウザが開く）
& aws sts get-caller-identity --profile $AwsProfile *> $null
if ($LASTEXITCODE -ne 0) {
    Invoke-Checked { aws login --region $Region --profile $AwsProfile } "aws login に失敗しました"
}

# Terraform の AWS プロバイダ v5 は aws login の認証を直接読めないため、一時認証情報を環境変数で渡す
# （キーは画面にもファイルにも出さない。環境変数はこの PowerShell を閉じると消える）
aws configure export-credentials --profile $AwsProfile --format powershell | Invoke-Expression

Invoke-Checked { terraform init -input=false } "terraform init に失敗しました"
Invoke-Checked { terraform plan -input=false -var "aws_profile=" -out=tfplan } "terraform plan に失敗しました"

Write-Host ""
Write-Host "上の plan の最後の行（Plan: X to add, Y to change, Z to destroy）を確認してください。"
Write-Host "初回は 16 to add / 0 to change / 0 to destroy になります。destroy があれば止めてください。"
$ans = Read-Host "この内容で AWS に作成（terraform apply）しますか？ (yes/no)"
if ($ans -ne "yes") {
    Write-Host "apply せずに終了しました。AWS には何も作っていません。"
    exit 0
}
Invoke-Checked { terraform apply -input=false tfplan } "terraform apply に失敗しました"

$dest = terraform output -raw rclone_dest
Write-Host ""
Write-Host "完了しました。次はラズパイで setup/2-pi-backup.sh を実行します。"
Write-Host "  BUCKET_NAME には $BucketName を書きます（rclone の保存先: $dest）"
Write-Host "  アクセスキーは、2-pi-backup.sh が聞いてきたときに AWS コンソールで発行します"
Write-Host "  （IAM → ユーザー → nas-backup → セキュリティ認証情報 → アクセスキーを作成）"
