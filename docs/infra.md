# Terraform（infra/）の解説

`infra/` の Terraform が AWS に何を作るのかを、ファイルごとに説明する。作り方の手順は [導入手順 1. AWS](setup-aws.md)、設計の理由は [仕様書の 5〜6章](spec.md#s3) を参照。

## 全体像

```
[ラズパイ rclone] --(nas-backup のアクセスキー, HTTPS)--> [S3 バケット (ap-southeast-2)]
                                                               ^
                         一覧とアップロードだけ許可（iam.tf）     |
                                                               |
[AWS Budgets 月5ドル] --実績100%--> [Budget Action] --書き込み拒否ポリシーを付ける--> [nas-backup]
[Cost Anomaly Detection] --サービス別の急増--> メール
```

作られるリソースは 15 個（2026-10-31 の `terraform plan` で確認）。すべてに `Project=nas-photo-backup`、`ManagedBy=terraform` のタグが付く。

| ファイル | 役割 | リソース数 |
|---|---|---|
| `versions.tf` | Terraform と AWS プロバイダのバージョン、リージョン、共通タグ | 0 |
| `variables.tf` | 入力値（バケット名、メール、予算額など） | 0 |
| `s3.tf` | 写真の保存先バケットと、その安全設定 | 6 |
| `iam.tf` | ラズパイ専用ユーザー `nas-backup` と最小権限ポリシー | 2 |
| `budget.tf` | 予算アラート、自動ストップ、異常検知 | 7 |
| `outputs.tf` | apply 後に表示する値 | 0 |
| `terraform.tfvars.example` | `terraform.tfvars` の雛形 | 0 |

## versions.tf

- Terraform 1.6 以上、AWS プロバイダ `~> 5.0`（2026-10 時点で v5.100.0 が入る）
- `provider "aws"` は `var.region` と `var.aws_profile` を使う
- `default_tags` で全リソースに共通タグを付ける。Cost Explorer でこのプロジェクトの費用だけを絞り込むときに使える

## variables.tf

| 変数 | 既定値 | 説明 |
|---|---|---|
| `region` | `ap-southeast-2` | 新しい AWS エクスペリエンスではプロジェクトのリージョン以外に作れないため、変更しない |
| `aws_profile` | `nas-admin` | apply に使う管理者プロファイル。環境変数で認証するときは空文字にする（[後述](#aws-login)） |
| `bucket_name` | なし（必須） | 世界で一意の名前。例 `example-nas-photo-backup` |
| `budget_email` | なし（必須） | 予算と異常検知の通知先 |
| `monthly_budget_usd` | `5` | 月額予算 |
| `backup_user_name` | `nas-backup` | ラズパイ用 IAM ユーザー名 |
| `anomaly_threshold_usd` | `1` | 異常検知でメールを送る金額の下限 |

実際の値は `terraform.tfvars`（Git 管理外）に書く。

## s3.tf {#s3}

| リソース | 設定 | 理由 |
|---|---|---|
| `aws_s3_bucket.backup` | `prevent_destroy = true` | `terraform destroy` や設定ミスでバックアップを消さない |
| `aws_s3_bucket_public_access_block.backup` | 4項目すべて `true` | 家族写真を誤って公開しない |
| `aws_s3_bucket_ownership_controls.backup` | `BucketOwnerEnforced` | ACL を無効にし、権限を IAM とバケットポリシーだけで管理する |
| `aws_s3_bucket_server_side_encryption_configuration.backup` | SSE-S3（AES256） | 追加料金なしで保存時に暗号化 |
| `aws_s3_bucket_lifecycle_configuration.backup` | 未完了マルチパートアップロードを7日で削除 | 中断したアップロードの断片に課金され続けるのを防ぐ |
| `aws_s3_bucket_policy.backup` | `aws:SecureTransport = false` なら `s3:*` を Deny | HTTPS 以外の通信を拒否 |

- `aws_s3_bucket_versioning`: バージョニングを有効にする。rclone は `--immutable` で上書きしないので普段は古い版ができず、費用は増えない。アクセスキーが漏れて同じ名前で上書きされた場合でも、元の写真が古い版として残る（`nas-backup` には古い版を消す権限がない）。一度有効にすると「停止」はできるが「無効」には戻せない（[セキュリティ点検の 1](security.md#versioning)）
- ストレージクラスはバケットではなく rclone 側（`storage_class = DEEP_ARCHIVE`）で指定する。料金は100GBで月約0.2ドル（[仕様書の 10章](spec.md#cost)）
- バケットポリシーは公開ブロックの後に作る（`depends_on`）

## iam.tf

`aws_iam_user.backup`（`nas-backup`）に、インラインポリシー `nas-backup-upload-only` を付ける。

| 操作 | 対象 | 用途 |
|---|---|---|
| `s3:ListBucket` | バケット | rclone が既存ファイルを確認する |
| `s3:PutObject` | `バケット/*` | アップロード |
| `s3:AbortMultipartUpload`、`s3:ListMultipartUploadParts` | `バケット/*` | 大きなファイルの分割アップロード |

- `GetObject`（読み出し）と `DeleteObject`（削除）は与えない。キーが漏れても写真を読まれたり消されたりしない
- アクセスキーは Terraform では作らない。作ると state ファイルにシークレットが平文で残るため、apply の後に AWS CLI で発行する（[導入手順 1 の「3. バックアップ用アクセスキーを発行する」](setup-aws.md#access-key)）

## budget.tf {#budget}

### 予算アラート

`aws_budgets_budget.monthly`（`nas-photo-backup-monthly`）。月5ドルのコスト予算で、次のときに `budget_email` へメールする。

- 実績が 80% を超えた
- 月末の予測が 100% を超えた

- フィルターを付けていないので、S3 だけでなくアカウント全体の料金が対象になる

アカウント全体の予算 `account-monthly-alert` は Terraform 管理外で手作業で作るため、名前を分けている。

### 自動ストップ（Budget Actions）

実績が予算の 100% に達すると、`nas-backup` に書き込み拒否ポリシーを自動で付ける。キーが漏れて大量にアップロードされた場合の被害を止めるためのもの。

| リソース | 内容 |
|---|---|
| `aws_iam_policy.backup_deny_write` | `nas-backup-deny-write`。`PutObject` などアップロード系と `ListBucket` を Deny |
| `aws_iam_role.budget_action` | `nas-backup-budget-action`。`budgets.amazonaws.com` だけが引き受けられる |
| `aws_iam_role_policy.budget_action` | `iam:AttachUserPolicy` / `DetachUserPolicy` を、対象 `nas-backup`・ポリシー `nas-backup-deny-write` に限って許可 |
| `aws_budgets_budget_action.stop_backup_writes` | `AUTOMATIC`（承認なし）で実行し、メールで通知 |

予算はアカウント全体の料金が対象なので、S3 以外が原因で5ドルを超えた場合もバックアップが止まる。解除方法は [料金の見張りと設定変更の「自動ストップが発動したら」](operations.md#auto-stop) を参照。

### 異常検知（Cost Anomaly Detection）

| リソース | 内容 |
|---|---|
| `aws_ce_anomaly_monitor.services` | `nas-photo-backup-services`。サービスごとに普段の課金を学習する |
| `aws_ce_anomaly_subscription.email` | `nas-photo-backup-anomaly`。影響額1ドル以上の異常を毎日メール |

## outputs.tf

| 出力 | 例 | 使い道 |
|---|---|---|
| `bucket_name` | `example-nas-photo-backup` | 確認用 |
| `backup_user_name` | `nas-backup` | アクセスキー発行の対象 |
| `rclone_dest` | `s3backup:example-nas-photo-backup/photos` | ラズパイの `/etc/nas-backup/backup.env` の `DEST` |

## 費用

apply で作るものはすべて作成時0円。

| 項目 | 費用 |
|---|---|
| 空の S3 バケット、IAM ユーザー・ロール・ポリシー | 無料 |
| AWS Budgets（予算、アクション付きは2個まで無料） | 無料 |
| Cost Anomaly Detection | 無料 |

課金が始まるのはラズパイが写真をアップロードしてから。

## aws login のプロファイルで実行するとき {#aws-login}

`aws login` で作ったプロファイルは AWS プロバイダ v5 から直接読めないため、一時認証情報を環境変数に出して実行する。手順は [導入手順 1 の「2. Terraform で作成する」](setup-aws.md#terraform) にある。
