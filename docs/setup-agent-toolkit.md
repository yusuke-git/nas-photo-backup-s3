# Agent Toolkit for AWS のセットアップ

AI コーディングツール（Claude Code など）から AWS を扱えるようにする [Agent Toolkit for AWS](https://github.com/aws/agent-toolkit-for-aws) の導入手順と、このリポジトリでの設定内容をまとめる。元の手順は [setup.md](https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/setup-instructions/setup.md)。

## 前提

| 項目 | 値 |
|---|---|
| AWS エクスペリエンス | 新しい AWS エクスペリエンス（AWS は「アカウント」ではなく「プロジェクト」と呼ぶ） |
| プロジェクトのリージョン | `ap-southeast-2`（シドニー） |
| Agent Toolkit サービスのリージョン | `us-east-1`（サービスがここにしかないため、手順 5・6 だけこの値を使う） |
| 作業場所 | 手元の PC（ブラウザでサインインするため） |
| 必要なツール | `curl`、`uv` |

認証は `aws login` のブラウザ認証で行う。アクセスキーは使わない。認証情報は12時間有効で、90日間はブラウザでの再サインインなしで更新できる。

## 手順

`<profile>` は AWS CLI のプロファイル名に置き換える。

1. OS を確認する（`uname -s`）
2. AWS CLI v2 を入れる（入っていれば不要）
   ```
   aws --version
   curl -fsSL 'https://awscli.amazonaws.com/v2/install.sh' | bash
   ```
3. リージョンを設定してサインインする（ブラウザが開く）
   ```
   aws configure set region ap-southeast-2 --profile <profile>
   aws login --region ap-southeast-2 --profile <profile>
   ```
4. 認証を確認する
   ```
   aws sts get-caller-identity --profile <profile>
   ```
5. Agent Toolkit を入れる（対話形式のウィザード）
   ```
   aws configure agent-toolkit --yes --region us-east-1 --profile <profile>
   ```
   生成された各 MCP 設定ファイルの `aws-mcp` エントリに、次の `env` を追加する（他の値は変えない）。入れないと `default` プロファイルを探して起動に失敗する。
   ```json
   "env": {
     "AWS_MCP_PROXY_PROFILES": "<profile>"
   }
   ```
6. 動作を確認する
   ```
   aws agent-toolkit list-available-skills --region us-east-1 --profile <profile>
   ```
7. ルールファイルを置く。新しい AWS エクスペリエンス用のルール（[aws-starter-rules.md](https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/rules/aws-starter-rules.md)）を、このリポジトリの `CLAUDE.md` の `BEGIN/END AWS Agent Toolkit rules` の間に入れてある。更新するときはこの間だけを置き換える。

手順 3〜6 は AWS への操作（サインイン、認証確認、Agent Toolkit サービスへの接続）を含むが、リソースは作らないので費用はかからない。

このリポジトリで実際に導入したときの記録は [構築記録](records.md#agent-toolkit) にある。

## つまずきやすい点

!!! note "Windows の日本語コンソールで出るエラー"
    `list-available-skills` の結果をそのまま表示すると `'cp932' codec can't encode character` で止まることがある。説明文中の記号をコンソールが表示できないだけで、API は正常に応答している。`--query 'skills[].name'` などで項目を絞るか、`$env:PYTHONIOENCODING="utf-8"` を設定してから実行する。

## Claude に渡す AWS 権限（読み取り専用）

`nas-admin` はフルアクセスのロール（`AccountFullAccessRole`）なので、Claude がふだん使う接続には使わない。

| プロファイル | 認証 | 権限 | 用途 |
|---|---|---|---|
| `nas-readonly` | IAM ユーザー `claude-viewonly` のアクセスキー（コンソールアクセスなし） | `ViewOnlyAccess` | Claude Code の aws-mcp（`AWS_MCP_PROXY_PROFILES`） |
| `nas-admin` | `aws login`（ブラウザ） | フルアクセス | `terraform apply` など変更作業。本人の承認を得てから使う |

- 新しい AWS エクスペリエンスでは高度な機能をオンにしていないため、IAM でマネジメントコンソールの権限を付けられない。そこで読み取り専用はアクセスキーの IAM ユーザーにした
- `ReadOnlyAccess` ではなく `ViewOnlyAccess` にしたのは、S3 のオブジェクトの中身（写真）を読めないようにするため
- キーは本人が `aws configure --profile nas-readonly` で入力する。チャットやリポジトリには書かない。使わなくなったらキーを無効にする
- `nas-admin` の `aws login` の認証情報は `aws logout --profile nas-admin` で消してある。変更作業のときだけサインインし直す

## 予算アラート（AWS Budgets）

2026-10-31 に `nas-admin` で CLI から作成した。プロジェクト全体の見張り役で、Terraform の管理外。

| 項目 | 値 |
|---|---|
| 名前 | `account-monthly-alert` |
| 予算 | 月 5 USD（コスト、毎月リセット） |
| 通知 | 実績が80%超、月末の予測が100%超で、本人のメールアドレスに通知 |
| 費用 | 無料（予算は2個まで無料） |

`infra/budget.tf` の `nas-photo-backup-monthly`（書き込み停止のアクション付き）とは名前が違うので、Terraform を適用してもぶつからない。両方作ると予算は2個で、無料の範囲に収まる。

## 別のプロジェクトを使うとき

`aws login --profile <name>` でサインインし、各 MCP 設定ファイルの `AWS_MCP_PROXY_PROFILES`（スペース区切り）にプロファイル名を足して、AI ツールを再起動する。

## 注意: Terraform のリージョン

新しい AWS エクスペリエンスでは、プロジェクトのリージョン以外にリソースを作れない。そのため `infra/variables.tf` の `region` の既定値と `backup/rclone.conf.example` のリージョンを、プロジェクトのリージョン `ap-southeast-2`（シドニー）に合わせた。`terraform.tfvars` で `region` を別の値にすると `terraform apply` が失敗するので変えない。
