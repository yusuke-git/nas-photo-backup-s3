# 用語集

このサイトに出てくる略語や専門用語の意味です。ページの中で初めて見る言葉があれば、ここで調べてください。

## AWS

| 用語 | 意味 |
|---|---|
| プロジェクト | 新しい AWS エクスペリエンスでの「AWS アカウント」の呼び方。このプロジェクトのリージョンは `ap-southeast-2`（シドニー）で、ほかのリージョンにはリソースを作れない |
| リージョン | AWS のデータセンターがある地域。`ap-southeast-2` はシドニー、`us-east-1` はバージニア北部 |
| S3 | AWS のファイル保存サービス（Amazon Simple Storage Service） |
| バケット | S3 の保存場所の単位。このドキュメントでは例として `example-nas-photo-backup` と書く（実際の名前は手元の `infra/terraform.tfvars`） |
| オブジェクト / キー | S3 に保存した 1 つ 1 つのファイルがオブジェクト、その名前（パス）がキー。例 `photos/2025/1203_誕生日/IMG_0001.jpg` |
| ストレージクラス | 保存料金と取り出しやすさの種類。Glacier Deep Archive（`DEEP_ARCHIVE`）は最も安い代わりに、取り出しに 12〜48 時間かかり、180 日以内に消すと残り日数分が課金される |
| SSE-S3 | S3 が保存時に自動で暗号化する方式（Server-Side Encryption with S3 managed keys）。追加料金なし。設定値は `AES256` |
| SSE-KMS | 鍵を AWS KMS（鍵の管理サービス）で管理する暗号化方式。料金がかかる |
| バージョニング | 同じ名前で上書きされても、古い版を残しておく S3 の機能 |
| ライフサイクル | 条件に合うオブジェクトを自動で消したり移したりする S3 の設定 |
| マルチパートアップロード | 大きなファイルを小分けにして送る方法。途中で止まると断片が残り、課金される |
| PUT / LIST / HEAD | S3 へのリクエストの種類。PUT はアップロード、LIST は一覧の取得、HEAD は 1 ファイルの情報の取得。どれも件数に応じて課金される |
| IAM | AWS の権限を管理するしくみ（Identity and Access Management） |
| IAM ユーザー | プログラムなどが AWS を使うための利用者。このプロジェクトではバックアップ用の `nas-backup` と、Claude の読み取り用の `claude-viewonly` |
| ポリシー | 「何をしてよいか・いけないか」を書いた IAM の設定。Allow（許可）と Deny（拒否）がある |
| アクセスキー | IAM ユーザーとしてプログラムから AWS を使うための ID とシークレットの組。漏れるとその権限で操作される |
| MFA | 多要素認証（Multi-Factor Authentication）。パスワードに加えてパスキーや FIDO2 セキュリティキーなどで本人確認する |
| SSO / IAM Identity Center | 1 回のサインインで AWS を使うしくみ（Single Sign-On）。アクセスキーを作らずに済む |
| `aws login` | ブラウザでサインインして AWS CLI の認証情報を得るコマンド |
| AWS Budgets | 月の予算を決め、超えそうになるとメールで知らせるサービス |
| Budget Actions | 予算を超えたときに、決めておいた操作（このプロジェクトでは書き込み拒否ポリシーを付ける）を自動で行う機能 |
| Cost Anomaly Detection | 普段と違う課金の増え方を見つけてメールで知らせるサービス |
| Agent Toolkit for AWS | Claude Code などの AI ツールから AWS を扱えるようにする AWS の道具一式 |

## Terraform

| 用語 | 意味 |
|---|---|
| Terraform | AWS などのリソースを設定ファイル（`.tf`）から作るツール |
| プロバイダ | Terraform が AWS などを操作するための部品。このプロジェクトは AWS プロバイダ v5 |
| `terraform plan` | 何が作られる・変わる・消えるかを、実行せずに表示する |
| `terraform apply` | plan の内容を実際に AWS に反映する |
| state | Terraform が作ったリソースを覚えておくファイル（`terraform.tfstate`）。管理用 PC にだけ置き、Git には入れない |
| `terraform.tfvars` | バケット名やメールアドレスなど、環境ごとの値を書くファイル。Git には入れない |

## ラズパイと NAS

| 用語 | 意味 |
|---|---|
| NAS | ネットワークにつなぐ HDD。このプロジェクトでは Buffalo LS220D2EE |
| SMB / CIFS | Windows のファイル共有の方式。Linux から SMB の共有をマウントするときは CIFS という名前で指定する。`vers=2.0` などはそのバージョン |
| マウント | NAS の共有フォルダを、ラズパイの `/mnt/nas/photos` などのフォルダとして見えるようにすること |
| fstab | 起動時に自動でマウントする設定ファイル（`/etc/fstab`） |
| `ro` / `rw` | マウントの種類。`ro` は読み取り専用（read-only）、`rw` は読み書き（read-write）。Docker の `:ro` も同じ意味 |
| rclone | ファイルをクラウドストレージに送るツール。詳しくは [backup.sh の解説](backup-script.md#rclone) |
| systemd timer | 決めた時刻にプログラムを起動する Linux のしくみ（cron の代わり） |
| flock | ファイルに鍵をかけて、同じスクリプトが二重に動くのを防ぐコマンド |
| logrotate | ログファイルを週ごとなどに切り替えて、古いものを消すしくみ |
| SSH | 別の PC からラズパイに入って操作するしくみ |
| デプロイキー | 1 つのリポジトリにだけ使える GitHub の SSH 鍵。ラズパイには読み取り専用で登録する |

## Immich と Tailscale

| 用語 | 意味 |
|---|---|
| Immich | 自分のサーバーで動かす写真閲覧アプリ |
| Docker / Docker Compose | アプリを「コンテナ」にまとめて動かすしくみ。Compose は複数のコンテナを 1 つのファイル（`docker-compose.yml`）でまとめて動かす |
| 外部ライブラリ | Immich の外にあるフォルダ（ここでは NAS の写真）を、コピーせずにそのまま取り込む Immich の機能 |
| ML（機械学習） | Immich の顔認識・スマート検索。Pi4 には重いので既定では無効 |
| Tailscale | 自分の端末どうしだけをつなぐ VPN サービス |
| tailnet | Tailscale で自分の端末どうしがつながったネットワーク |
| `tailscale serve` / `funnel` | `serve` は tailnet の中だけに公開、`funnel` はインターネットに公開する。このプロジェクトでは `funnel` は使わない |
