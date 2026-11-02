# 導入手順 1. AWS（Terraform）

S3 バケット、IAM ユーザー、予算アラートを `infra/` の Terraform で作る。作業は手元の PC で行う。各リソースの中身は [Terraform の解説](infra.md)、設計の理由は [仕様書の 5〜6章](spec.md#s3) を参照。

## 作られるもの

| リソース | 内容 | 費用 |
|---|---|---|
| S3 バケット | シドニーリージョン（`ap-southeast-2`）、SSE-S3 暗号化、パブリックアクセス全ブロック、HTTPS 以外を拒否、バージョニング有効（上書きされても古い版が残る）、未完了アップロードを7日で削除 | 作成時は0円（保存した分だけ課金） |
| IAM ユーザー `nas-backup` | 一覧とアップロードだけ。削除・読み出しの権限なし | 無料 |
| AWS Budgets | 月5ドル。実績80%、予測100%でメール通知 | 無料（2個まで） |
| Budget Actions | 実績が予算の100%に達したら、`nas-backup` に書き込み拒否ポリシーを自動で付ける | 無料 |
| Cost Anomaly Detection | サービスごとの課金の急増（1ドル以上）を毎日メールで通知 | 無料 |

`terraform apply` そのものでは費用は発生しない。費用が発生するのは、ラズパイのバックアップが写真をアップロードしてから（[仕様書の 10章 費用見積もり](spec.md#cost)）。

!!! warning "バケットは terraform destroy で消せない"
    バックアップを誤って消さないよう `prevent_destroy` を付けている。本当に消すときは、この設定を外してから実行する。Deep Archive は180日以内に消すと残り日数分が課金される点にも注意する。

## 1. AWS アカウントの準備（コンソールで手作業） {#account}

1. AWS アカウントを作る
2. ルートユーザーに MFA を設定する
3. 作業用の管理者ユーザーを作る（IAM Identity Center を推奨。IAM ユーザーなら `AdministratorAccess` を付けて MFA を設定）
4. 手元の PC に AWS CLI と Terraform（1.6 以上）を入れ、プロファイル `nas-admin` を設定する
   ```
   aws login --region ap-southeast-2 --profile nas-admin   # 新しい AWS エクスペリエンスの場合
   aws sts get-caller-identity --profile nas-admin
   ```

## 2. Terraform で作成する {#terraform}

```
cd infra
cp terraform.tfvars.example terraform.tfvars   # bucket_name と budget_email を編集
terraform init
terraform plan -out=tfplan    # 作られるものを確認
terraform apply tfplan        # 確認した plan をそのまま適用
```

!!! note "`aws login` のプロファイルを使う場合"
    Terraform の AWS プロバイダ（v5）は `aws login` の認証情報を直接読めず、`No valid credential sources found` になる。一時認証情報を環境変数に入れ、`aws_profile` を空にして実行する（PowerShell）。
    ```
    aws login --region ap-southeast-2 --profile nas-admin
    aws configure export-credentials --profile nas-admin --format powershell | Invoke-Expression
    terraform plan -var aws_profile= -out=tfplan
    terraform apply tfplan
    ```
    環境変数はシェルを閉じると消える。キーを画面やファイルに出さない。`tfplan`、`terraform.tfvars`、`*.tfstate` は Git に入れない（`.gitignore` 済み）。

- `bucket_name` は世界で一意にする（例 `example-nas-photo-backup-2026`）
- 予算アラートのメールは、AWS から届く確認メールの承認は不要（Budgets は直接送信）
- `terraform.tfstate` は手元に保存される。秘密情報は含まないが、バケット名などが入るので Git には入れない（`.gitignore` 済み）

## 3. バックアップ用アクセスキーを発行する {#access-key}

キーを Terraform の state に残さないよう、apply の後に本人が発行する（Claude などのツールにキーを見せない、チャットに貼らない）。

- コンソール: IAM → ユーザー → `nas-backup` → セキュリティ認証情報 → アクセスキーを作成（用途は「AWS の外部で実行されるアプリケーション」）
- CLI:
  ```
  aws iam create-access-key --user-name nas-backup --profile nas-admin
  ```

表示された `AccessKeyId` と `SecretAccessKey` を、ラズパイの `~/.config/rclone/rclone.conf` に記入する（[導入手順 2 の「4. rclone の設定」](setup-backup.md#rclone)）。シークレットは再表示できないので、その場で記入する。

## 4. ラズパイ側の設定 {#raspi}

```
terraform output rclone_dest    # 例: s3backup:example-nas-photo-backup/photos
```

この値を `/etc/nas-backup/backup.env` の `DEST` に書き、[導入手順 2 の「5. 試運転」](setup-backup.md#dry-run)から進める。

## 次にやること

- ラズパイの設定は [導入手順 2. バックアップ](setup-backup.md) へ進む
- 予算を超えて書き込みが止まったときや、`infra/` の設定を変えるときは [料金の見張りと設定変更](operations.md) を参照
- いつ何を作ったかは [構築記録](records.md#aws) に残している
