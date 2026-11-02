# クイックスタート（スクリプトで組み立てる）

`setup/` の 3 本のスクリプトで、AWS → バックアップ → Immich の順に組み立てる。各スクリプトは冒頭の「設定」を書き換えてから実行する。中で何をしているかは、手動の手順（[1. AWS](setup-aws.md)、[2. バックアップ](setup-backup.md)、[3. Immich](setup-immich.md)）と同じ。

| スクリプト | 実行する場所 | すること | AWS の操作 |
|---|---|---|---|
| `setup/1-aws.ps1`（Windows）<br>`setup/1-aws.sh`（Mac / Linux） | 手元の PC | `terraform.tfvars` を作り、`aws login` → `terraform plan` → 確認して `apply` | あり（plan を見て `yes` と入力したときだけ apply） |
| `setup/2-pi-backup.sh` | ラズパイ | パッケージ、NAS のマウント、rclone のキー、`backup.env`、試運転、確認して本番とタイマー | 試運転は一覧の取得だけ。本番は `yes` と入力したときだけ |
| `setup/3-pi-immich.sh` | ラズパイ | Docker、`.env`（DB のパスワードは自動生成）、NAS 待ちの設定、`docker compose up` | なし |

## 0. 事前の準備（手作業）

- AWS のアカウント（新しい AWS エクスペリエンスならプロジェクト）。ルートに MFA を付け、管理者で `aws login` できるようにしておく
- 手元の PC に AWS CLI v2 と Terraform 1.6 以上
- NAS の管理画面で、ラズパイ専用ユーザー（例 `nas-pi`）を作り、`Photo` 共有に**読み取りのみ**、`Thumbnail` 共有に**読み書き**を許可する（[2. バックアップ](setup-backup.md) の 2 章）
- ラズパイに Raspberry Pi OS（64bit）を入れ、SSH で入れるようにする

## 1. AWS（手元の PC）

```powershell
git clone https://github.com/yusuke-git/nas-photo-backup-s3.git nas-photo-backup
cd nas-photo-backup
notepad setup\1-aws.ps1          # 冒頭の BucketName と BudgetEmail を書き換える
powershell -ExecutionPolicy Bypass -File setup\1-aws.ps1
```

Mac / Linux は `setup/1-aws.sh` を編集して `bash setup/1-aws.sh`。

- plan の最後が `16 to add, 0 to change, 0 to destroy` なら `yes` と入力する
- state（`terraform.tfstate`）はこのフォルダの `infra/` にできる。以後の Terraform の作業は必ずこのフォルダで行う（別の場所に clone して plan すると、全部を新しく作ろうとする）

## 2. バックアップ（ラズパイ）

```bash
sudo apt-get install -y git
sudo install -d -o "$USER" -g "$USER" /opt/nas-photo-backup
git clone https://github.com/yusuke-git/nas-photo-backup-s3.git /opt/nas-photo-backup
cd /opt/nas-photo-backup
nano setup/2-pi-backup.sh        # 冒頭の NAS_IP と BUCKET_NAME を書き換える
bash setup/2-pi-backup.sh
```

途中で sudo のパスワード、NAS のパスワード、AWS のアクセスキーを聞かれる。アクセスキーは聞かれたときに AWS コンソール（IAM → ユーザー → `nas-backup` → アクセスキーを作成）で発行して貼り付ける。キーはラズパイの `~/.config/rclone/rclone.conf` にだけ保存される。

最後に試運転の件数（拡張子ごと）と初回の料金の目安が出る。想定どおりなら `yes` で本番のアップロードと毎晩 02:00 のタイマーが始まる。

## 3. Immich（ラズパイ）

```bash
cd /opt/nas-photo-backup
nano setup/3-pi-immich.sh        # SD カードで動かすなら DB_STORAGE_TYPE="HDD"
bash setup/3-pi-immich.sh
```

終わったら表示された `http://<ラズパイのIP>:2283` を開いて管理者を作り、「管理」→「外部ライブラリ」でフォルダ `/mnt/media/photos` を登録してスキャンする。

## もう一度実行したとき

- どのスクリプトも、作成済みのファイル（`/etc/nas-credentials`、`rclone.conf`、`backup.env`、`.env`、`/etc/fstab` の行）は上書きしない。やり直したいときは、そのファイル（fstab は該当行）を消してから実行する
- `2-pi-backup.sh` は、本番を `no` で見送ったあとにもう一度実行すれば、試運転から続きができる
- `1-aws.ps1` / `1-aws.sh` は、`infra/*.tf` を変えたあとの `plan` と `apply` にも使える（`terraform.tfvars` を書き換えるかどうかは聞かれる）
