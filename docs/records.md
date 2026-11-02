# 構築記録

実際の環境に対して、いつ・何をしたかの記録。手順そのものは各ページを参照。新しく作業したら、該当する表や箇条書きに追記する。

## AWS（Terraform） {#aws}

[導入手順 1. AWS](setup-aws.md) の作業と、そのあとの `infra/` の変更の記録。

リポジトリを公開するため、実際のバケット名は例の名前（`example-nas-photo-backup`）に置き換えている。実際の値は手元の `infra/terraform.tfvars` を見る。

| 日付 | 内容 |
|---|---|
| 2026-10-31 | `terraform apply` で15リソースを作成（変更・削除なし）。バケット `example-nas-photo-backup`（`ap-southeast-2`、`get-bucket-location` で確認）、ユーザー `nas-backup`、予算 `nas-photo-backup-monthly`（月5ドル、Budget Action は STANDBY）、異常検知 `nas-photo-backup-anomaly`。Terraform v1.16.6、AWS プロバイダ v5.100.0。state は管理用 PC の `infra/terraform.tfstate`。アカウント全体の予算 `account-monthly-alert` は Terraform 管理外（手作業） |
| 2026-11-02 | `terraform apply` でバケットのバージョニングを有効化（1追加、1変更、削除なし）。変更は `nas-backup` ユーザーのタグ削除（コンソールでアクセスキーを作ったときの説明「nas-pi」。キーと権限は変わらない）。`aws_iam_role_policy.budget_action` は plan で再計算と表示されたが、中身が同じため変更なし。state の場所は管理用 PC の 管理用 PC の決まったフォルダの `infra`（ほかの clone には state がないので、そこで plan しない） |

## Agent Toolkit for AWS（2026-10-31） {#agent-toolkit}

[Agent Toolkit for AWS](setup-agent-toolkit.md) を導入したときの記録。

- 手元の PC: Windows 11 Pro。curl と uv は導入済みだった
- プロファイル名: `nas-admin`（`~/.aws/config` に `region = ap-southeast-2` で新規作成）
- AWS CLI: `winget install --id Amazon.AWSCLI -e` を本人が手動で実行して導入（aws-cli/2.39.3）。Claude Code の安全チェックは、スクリプトをパイプで実行する公式インストーラも、規約同意オプション付きの winget も止めるため、インストールだけは本人が行う
- `sts get-caller-identity`: `AccountFullAccessRole` のロールでサインインしていることを確認
- Agent Toolkit: 検出された AI ツールは Claude Code のみ。デフォルトのスキル24個を `~/.claude/skills` に導入し、`~/.claude.json` の `aws-mcp` エントリに `AWS_MCP_PROXY_PROFILES=nas-admin` を追加した。設定を反映するには Claude Code を再起動する
- 動作確認: `list-available-skills` で118件のスキルを取得できた
