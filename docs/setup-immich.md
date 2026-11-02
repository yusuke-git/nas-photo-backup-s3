# 導入手順 3. Immich

!!! tip "スクリプトでまとめて実行する"
    この手順は `setup/3-pi-immich.sh` でまとめて実行できる。[クイックスタート](quickstart.md) を参照。

ラズパイ（Raspberry Pi 4）で [Immich](https://immich.app/) を動かし、NAS の写真を外部ライブラリとして読み取り専用で取り込む。NAS のマウントは [導入手順 2 の「1. パッケージ」「2. NAS のマウント」](setup-backup.md#packages) を先に済ませておく。設計の理由は [仕様書の 8章](spec.md#immich) を参照。

## 0. 前提

| 項目 | 条件 |
|---|---|
| OS | Raspberry Pi OS **64bit**（`uname -m` が `aarch64`） |
| メモリ | 4GB 以上（8GB 推奨）。4GB の場合は機械学習を無効のまま使う |
| ディスク | USB 接続の SSD を推奨（`/srv/immich` にマウント）。DB と動画変換などを置く。サムネイルは NAS に置く |
| NAS | `Photo` を `/mnt/nas/photos` に読み取り専用、`Thumbnail` を `/mnt/nas/thumbnail` に読み書きでマウント済み |
| NAS の空き | サムネイル用に写真 2 万枚でおよそ 5〜10GB |

SD カードだけでも動くが、DB の書き込みでカードが傷みやすい。SD カードで動かす場合は `.env` の `DB_STORAGE_TYPE=HDD` にする。

## 1. Docker のインストール

```
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker pi        # 反映には再ログインが必要
docker compose version
```

## 2. 置き場所と設定ファイル

```
sudo mkdir -p /srv/immich/library /srv/immich/postgres
cd /opt/nas-photo-backup/immich
sudo cp example.env .env
sudo chmod 600 .env
sudo nano .env                    # DB_PASSWORD を変える（openssl rand -hex 24 の結果など）
```

## 3. NAS のマウントを待ってから起動するようにする

```
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo cp /opt/nas-photo-backup/immich/systemd/docker.service.d/wait-nas.conf /etc/systemd/system/docker.service.d/
sudo systemctl daemon-reload
```

起動直後に NAS がまだマウントされていないと、スキャンで写真が「オフライン」扱いになるのを防ぐため。

## 4. 起動

```
cd /opt/nas-photo-backup/immich
docker compose up -d
docker compose ps                 # 4 つではなく 3 つ（server / redis / database）が動いていれば正常
docker exec immich_server ls /mnt/media/photos   # 年フォルダが見えることを確認
docker exec immich_server ls -a /data/thumbs      # .immich ができていれば NAS に書けている
```

初回はイメージのダウンロードに数分かかる。

## 5. 初期設定（ブラウザ）

1. 同じ LAN の PC から `http://<ラズパイのIP>:2283` を開き、管理者アカウントを作る
2. 「管理」→「外部ライブラリ」→「ライブラリを作成」
    - 所有者: 自分（あとから変更できない）
    - フォルダ: `/mnt/media/photos`（コンテナ内のパスを書く。`/mnt/nas/photos` ではない）
3. 「スキャン」を押す。初回は写真の枚数に応じて数時間〜1日かかる（Pi4 でサムネイル生成は 1 枚あたり 1 秒前後が目安）
4. 「アカウント設定」→「機能」で「フォルダ」を有効にすると、`年/MMDD_イベント` の並びで見られる

新しい写真は 6 時間ごとの自動スキャンで取り込まれる。すぐに見たいときは「外部ライブラリ」でスキャンを押す。

## 6. スマホから見る

- Immich アプリ（iOS / Android）を入れ、サーバー URL に `http://<ラズパイのIP>:2283` を入れる
- 家の外から見る場合は下の「外部アクセス（Tailscale）」を参照
- アプリの「バックアップ」（スマホからの自動アップロード）を使うと、写真は NAS ではなくラズパイの `/srv/immich/library` に入り、S3 にもバックアップされない。写真は今まで通り PC から NAS に保存する

## 7. 外部アクセス（Tailscale）

ルーターのポートは開けず、[Tailscale](https://tailscale.com/)（個人利用は無料）で自分の端末からだけつなぐ。

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                 # 表示された URL を開いてログイン
tailscale ip -4                   # 100.x.y.z が割り当てられる
```

スマホにも Tailscale アプリを入れて同じアカウントでログインし、Immich アプリのサーバー URL に `http://<ラズパイのTailscale名またはIP>:2283` を入れる。HTTPS にしたい場合は `sudo tailscale serve --bg 2283` で `https://<ラズパイ名>.<tailnet名>.ts.net` から開ける。

## 公式構成との違い {#diff-from-official}

`immich/docker-compose.yml` は公式ファイルを元に次の点だけ変えている。Immich を更新するときは、新しいリリースの公式ファイルと見比べる。

| 変更 | 理由 |
|---|---|
| `${PHOTOS_LOCATION}:/mnt/media/photos:ro` を追加 | NAS の元写真を読み取り専用（末尾の `:ro` = read-only）で外部ライブラリにする。Immich の画面から削除しても元写真は消えない |
| `${THUMB_LOCATION}:/data/thumbs` を追加 | サムネイルを NAS の `Thumbnail` 共有に置き、ラズパイのディスクを節約する（Immich 公式の「カスタムの保存場所」の方法） |
| 機械学習コンテナを `profiles: ['ml']` に入れた | Pi4 では顔認識・スマート検索が重いので既定では起動しない |
| `IMMICH_CONFIG_FILE` で `immich-config.json` を読む | 設定を Git で管理する。この設定は画面から変更できなくなる |
| `DB_STORAGE_TYPE` を `.env` で切り替え | SSD 以外に DB を置く場合の性能対策 |

## サーバー設定（immich-config.json）

| 設定 | 値 | 理由 |
|---|---|---|
| `machineLearning.enabled` | `false` | 機械学習コンテナを動かさないため |
| `library.scan.cronExpression` | `0 */6 * * *` | 6 時間ごとに NAS を再スキャン（既定は 1 日 1 回） |
| `library.watch.enabled` | `false` | ネットワーク共有ではファイル監視が動かないため |
| `job.*.concurrency` | 1〜2 | Pi4 の CPU とメモリに合わせて既定より減らす |

書かなかった項目は Immich の既定値になる。設定を変えたら `docker compose up -d --force-recreate immich-server` で反映する。

## 機械学習を有効にする（任意、8GB モデル向け）

1. `immich-config.json` の `machineLearning.enabled` を `true` にする
2. `docker compose --profile ml up -d`
3. 「管理」→「ジョブ」で「スマート検索」「顔検出」を実行する（初回は数日かかることがある）

## 更新

```
cd /opt/nas-photo-backup && git pull
cd immich && docker compose pull && docker compose up -d
```

更新前に [リリースノート](https://github.com/immich-app/immich/releases) で「Breaking changes」を確認する。メジャー更新（v3 → v4 など）は `.env` の `IMMICH_VERSION` を変えるまで入らない。

## データの保護

- 元写真: NAS にあり、S3 Deep Archive にもバックアップ済み。Immich からは読むだけ
- Immich の DB（アルバム、お気に入り、説明文など）: Immich が毎日 `/srv/immich/library/backups/` に自動でダンプを作る。ラズパイの SSD が壊れるとアルバムなどは失われるが、写真は失われない。サムネイルは再スキャンで作り直せる
- ダンプを NAS や S3 にも送るかは未決（[仕様書の 11章 未決事項](spec.md#open-issues)）

## 止める・元に戻す

```
cd /opt/nas-photo-backup/immich
docker compose down               # 停止（データは残る）
sudo rm -rf /srv/immich           # Immich のデータを消す（NAS の写真には影響しない）
```
