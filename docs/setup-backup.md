# 導入手順 2. バックアップ

ラズパイ（Raspberry Pi OS）上で実行する。AWS 側の準備（バケットと IAM ユーザー、アクセスキー）は [導入手順 1. AWS](setup-aws.md) で先に済ませておく。`backup.sh` の中身は [backup.sh の解説](backup-script.md)、設計の理由は [仕様書の 4章と 7章](spec.md#nas-mount) を参照。

## 1. パッケージ {#packages}

```
sudo apt update
sudo apt install -y cifs-utils rclone
```

## 2. NAS のマウント {#nas-mount}

### ラズパイ専用の NAS ユーザーを作る

普段使いのユーザーを使い回さず、ラズパイ専用のユーザー `nas-pi` を NAS に作る。ラズパイが乗っ取られても、NAS の写真を消したり他の共有を見たりできないようにするため。

1. NAS の管理画面（Web）で、ユーザー `nas-pi` を追加する（パスワードは長いランダムなもの）
2. 共有フォルダー `Photo` のアクセス制限で、`nas-pi` に**読み取り専用**を付ける
3. 共有フォルダー `Thumbnail` には `nas-pi` に**読み書き**を付ける
4. ほかの共有フォルダーには `nas-pi` の権限を付けない

`Photo` はラズパイ側のマウントも読み取り専用（fstab の `ro` = read-only）にしているが、NAS 側でも読み取り専用にしておくと二重の防御になる。

### マウント

```
sudo mkdir -p /mnt/nas/photos /mnt/nas/thumbnail
sudo install -m 600 /dev/null /etc/nas-credentials   # username=nas-pi / password= を記入
cat backup/fstab.example                              # 2行を /etc/fstab に追記し、<NASのIP> を置き換える
sudo systemctl daemon-reload
sudo mount -a && ls /mnt/nas/photos /mnt/nas/thumbnail
touch /mnt/nas/thumbnail/.write-test && rm /mnt/nas/thumbnail/.write-test   # 書き込めることを確認
```

## 3. リポジトリの配置 {#repo}

リポジトリはプライベートなので、ラズパイ専用の読み取り専用デプロイキーで clone する。

```
ssh-keygen -t ed25519 -f ~/.ssh/nas-photo-backup -N "" -C "raspi deploy key"
cat ~/.ssh/nas-photo-backup.pub   # GitHub の Settings → Deploy keys に登録（Allow write access は付けない）
sudo install -d -o pi -g pi /opt/nas-photo-backup
GIT_SSH_COMMAND="ssh -i ~/.ssh/nas-photo-backup" git clone git@github.com:<user>/<repo>.git /opt/nas-photo-backup
git -C /opt/nas-photo-backup config core.sshCommand "ssh -i ~/.ssh/nas-photo-backup"   # 以降の git pull も同じ鍵を使う
```

```
sudo mkdir -p /etc/nas-backup /var/log/nas-backup
sudo chown pi:pi /var/log/nas-backup
sudo cp /opt/nas-photo-backup/backup/backup.env.example /etc/nas-backup/backup.env   # DEST を編集
sudo cp /opt/nas-photo-backup/backup/logrotate.conf /etc/logrotate.d/nas-backup
```

## 4. rclone の設定 {#rclone}

```
mkdir -p ~/.config/rclone
cp /opt/nas-photo-backup/backup/rclone.conf.example ~/.config/rclone/rclone.conf
chmod 600 ~/.config/rclone/rclone.conf   # キーを記入
```

記入するキーは [導入手順 1 の「3. バックアップ用アクセスキーを発行する」](setup-aws.md#access-key) で発行したもの。

## 5. 試運転（料金はかからない） {#dry-run}

```
DRY_RUN=1 /opt/nas-photo-backup/backup/backup.sh
tail /var/log/nas-backup/backup.log
```

対象ファイルの一覧がログに出ることを確認する。`DRY_RUN=1` では一覧の取得（LIST リクエスト、ほぼ無料）しか行わない。

## 6. 本番実行と自動化 {#run}

初回はアップロードのリクエスト料金がかかる（1,000枚あたり約0.06ドル、100GB・約2万枚で約1〜2ドル）。以降は新しい写真の分だけ。

```
/opt/nas-photo-backup/backup/backup.sh       # 初回を手動で実行
sudo cp /opt/nas-photo-backup/backup/systemd/nas-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nas-backup.timer
systemctl list-timers nas-backup.timer
```

## 動作の要点

- `rclone copy --immutable`: S3 のファイルを削除・上書きしない。同じ名前でサイズが違うファイルはエラーとしてログに残る
- `--size-only` と `--s3-no-head`: ファイルごとの HEAD リクエストを省き、毎日の差分確認を一覧取得だけで済ませる（2TB・約40万枚でも1日数円以下）
- NAS がマウントされていないときは何もせずに終了する
- 二重起動は `flock` で防ぐ
