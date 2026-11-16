# 導入手順 4. 機械学習を Windows PC で動かす（リモート ML）

Pi4 では重すぎる顔検出・スマート検索・OCR を、家の Windows PC に肩代わりさせる。Mac も予備として登録し、Windows PC が止まっているときは Mac が処理する。Immich の公式機能「[Remote Machine Learning](https://docs.immich.app/guides/remote-machine-learning)」を使う。[導入手順 3. Immich](setup-immich.md) を済ませてから進める。

## 仕組み

```
[ラズパイ]                                                   [Windows PC / Mac]
 immich_server ──> 中継 ml-relay ──(LAN, 名前で接続 :3003)──> immich_machine_learning
 (コンテナ)        (ラズパイ本体)    desktop-abc123.local      顔の位置・特徴、画像の特徴を返す
   └─ 結果を PostgreSQL に保存。顔のグループ分け（顔認識）はラズパイ側で行う
```

- **固定 IP は不要**。PC は IP ではなく名前（mDNS の `xxx.local`）で探す。Windows 10/11 と Mac は、LAN に自分の名前を自動で知らせている
- Immich はコンテナの中で動いていて、コンテナからは `.local` の名前を引けない。そこでラズパイ本体に小さな中継（`immich/ml-relay/`、socat）を置き、本体で名前を引いて PC につなぐ。接続のたびに引き直すので、PC の IP が変わっても追従する
- Immich の設定（`immich-config.json`）には中継の宛先 `http://host.docker.internal:3101`（Windows）と `:3102`（Mac）だけを書く。どの家でも同じなので Git にそのまま入れられる。PC の名前は各家庭の `immich/.env` に書く

- PC に送られるのはプレビュー画像だけ。元写真は送らず、PC 側にも保存されない
- 通信は家の LAN の中だけで完結し、AWS は使わない（料金への影響なし）
- 重いのは最初の全件処理。そのあとは新しく取り込んだ写真の分だけになる
- PC の電源が切れている間は機械学習のジョブが失敗するだけで、閲覧・スキャン・バックアップは普段どおり動く

## 0. 前提

| 項目 | 条件 |
|---|---|
| PC | Windows 10/11（64bit）、メモリ 8GB 以上 |
| Docker | [Docker Desktop](https://www.docker.com/products/docker-desktop/)（WSL 2 バックエンド） |
| ネットワーク | PC とラズパイが同じ LAN。固定 IP やルーターの設定は不要 |
| Mac（任意、予備） | Apple シリコン（M1 以降）または Intel Mac、[Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)。Docker からは Apple の GPU を使えないため CPU で動く |
| GPU（任意） | NVIDIA なら CUDA、Intel 内蔵 GPU なら OpenVINO で速くなる。なくても CPU で動く |

## 1. PC で機械学習コンテナを起動する

リポジトリを PC に clone（またはダウンロード）し、PowerShell で次を実行する。

```
cd <リポジトリ>\immich\remote-ml
copy example.env .env
notepad .env                      # IMMICH_VERSION をラズパイ側の immich/.env と同じにする
docker compose up -d
docker compose logs -f            # "Application startup complete" が出れば起動済み（Ctrl+C で抜ける）
```

CPU で動かすなら `.env` は `example.env` をコピーしたままでよい（`ML_ACCEL=` は `=` の後ろを空のままにする）。`.env` で使われるのは `IMMICH_VERSION` と `ML_ACCEL` の 2 つだけ。

### GPU を使う（任意） {#gpu}

GPU を使うときは、**`.env` と `docker-compose.yml` の 2 か所** を変える。片方だけでは GPU は使われない。

| 使う GPU | ① `.env` に書く値 | ② `docker-compose.yml` で行頭の `# ` を外す行 |
|---|---|---|
| なし（CPU） | `ML_ACCEL=`（空のまま） | なし（編集しない） |
| NVIDIA（GeForce など） | `ML_ACCEL=-cuda` | 【NVIDIA】の印の下の 8 行（`deploy:` から `- gpu` まで） |
| Intel の内蔵 GPU / Arc | `ML_ACCEL=-openvino` | 【Intel】の印の下の 2 行（`devices:` と `- /dev/dxg:/dev/dxg`）と、`volumes:` の中の【Intel】の 1 行（`- /usr/lib/wsl:/usr/lib/wsl`） |

外すのは行頭の `# `（シャープと空白 1 つ）だけで、字下げは残す。たとえば NVIDIA の場合、外したあとはこうなる（`deploy:` は上の `healthcheck:` と同じ字下げになる）。

```
    healthcheck:
      disable: false

    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities:
                - gpu
```

Intel の場合は次のようになる。

```
    volumes:
      - model-cache:/cache
      - /usr/lib/wsl:/usr/lib/wsl
    （中略）
    devices:
      - /dev/dxg:/dev/dxg
```

書き換えたら、反映して確かめる。

```
docker compose config             # エラーが出なければ書き方は合っている（字下げがずれているとここで分かる）
docker compose up -d              # GPU 用のイメージに入れ替わる（初回は数 GB のダウンロード）
docker compose ps                 # IMAGE の末尾が -cuda または -openvino になっていること
```

ジョブの実行中に、タスクマネージャーの「パフォーマンス」で GPU の使用率が上がっていれば GPU で動いている。NVIDIA は Windows 側に最新のドライバーが入っていれば WSL 2 から使える。CPU に戻すときは 2 か所を元に戻して `docker compose up -d`。

### Mac でも起動する（予備）

ターミナルで同じ構成を起動する。公式イメージは Apple シリコン（arm64）にも対応している。`.env` の `ML_ACCEL` は空のまま（CPU）にする。

```
cd <リポジトリ>/immich/remote-ml
cp example.env .env
open -e .env                      # IMMICH_VERSION をラズパイ側と同じにする
docker compose up -d
```

Mac のファイアウォールを有効にしている場合は、受信の許可を求められたら許可する。

## 2. PC の名前を調べる

| PC | 調べ方 | 書く名前の例 |
|---|---|---|
| Windows | 「設定」→「システム」→「バージョン情報」の「デバイス名」 | `desktop-abc123.local`（デバイス名に `.local` を付ける。大文字小文字は区別しない） |
| Mac | 「システム設定」→「一般」→「共有」のいちばん下、「ローカルホスト名」 | `my-mac.local` |

ラズパイで名前が引けるか確かめる。IP が表示されれば OK。

```
getent hosts desktop-abc123.local
getent hosts my-mac.local
curl http://desktop-abc123.local:3003/ping     # pong と返れば機械学習コンテナまで届いている
```

届かない場合は Windows のネットワーク設定を確認する。

- 「設定」→「ネットワークとインターネット」で、家の Wi-Fi / 有線が「**プライベート**ネットワーク」になっていること。「パブリック」だと Windows は名前に応答せず、ポート 3003 も受け付けない
- それでもポート 3003 に届かなければ、管理者の PowerShell で受信を許可する（プライベートネットワークだけに限定する）

```
New-NetFirewallRule -DisplayName "Immich ML (LAN)" -Direction Inbound -Protocol TCP -LocalPort 3003 -Profile Private -Action Allow
```

mDNS が使えない環境では、[Tailscale](setup-immich.md#tailscale) の名前（例: `windows-pc`）や IP を書いてもよい。

## 3. ラズパイに PC の名前を登録する

**スクリプトで行う場合**: `setup/3-pi-immich.sh` の冒頭の `ML_PRIMARY_HOST`（Windows）と `ML_BACKUP_HOST`（Mac）に名前を書いて実行する。`.env` への書き込み、中継の導入、Immich の再起動までを行う。

**手で行う場合**:

```
cd /opt/nas-photo-backup/immich
nano .env          # ML_PRIMARY_HOST=desktop-abc123.local と ML_BACKUP_HOST=my-mac.local を書く
sudo apt-get install -y socat avahi-daemon libnss-mdns
sed "s|@REPO_DIR@|/opt/nas-photo-backup|" ml-relay/immich-ml-relay@.service | sudo tee /etc/systemd/system/immich-ml-relay@.service
sudo systemctl daemon-reload
sudo systemctl enable --now immich-ml-relay@primary immich-ml-relay@backup
docker compose up -d --force-recreate immich-server
systemctl status immich-ml-relay@primary      # 「中継: 172.17.0.1:3101 -> desktop-abc123.local:3003」と出ていれば OK
```

`immich-config.json` の `machineLearning.urls` は `http://host.docker.internal:3101`（Windows）、`http://host.docker.internal:3102`（Mac）の順。URL は上から順に試され、応答した最初の 1 台がすべての処理をする（2 台に振り分けて並列処理はしない）。Windows PC が止まっていれば Mac が処理し、両方止まっていればジョブが失敗する。Immich は 30 秒ごとに各 URL が応答するかを確かめている。Mac を使わない場合は `ML_BACKUP_HOST` を空にしておけばよい（`:3102` は応答しないだけ）。

中継はラズパイの Docker のブリッジ（`docker0`）でだけ待ち受けるので、LAN の他の機器からは見えない。ラズパイ側の機械学習コンテナ（`ml` profile）は起動しないので、PC が両方止まっているときにラズパイで重い処理が走ることはない。

PC の名前を変えたときは `.env` を直して `sudo systemctl restart immich-ml-relay@primary immich-ml-relay@backup`。

## 4. 初回の全件処理

1. ブラウザで Immich を開き、「管理」→「ジョブ」（Job Status）
2. 「スマート検索」「顔検出」「OCR」を **すべて**（All）で実行する
3. 顔検出が終わると「顔認識」（顔のグループ分け）が自動で続く。こちらはラズパイ側の処理

処理中は PC のタスクマネージャーで CPU / GPU が使われていることを確認できる。終わるまでは PC をスリープさせない。

## 普段の運用

- 新しい写真は 6 時間ごとのスキャンで取り込まれ、そのとき Windows PC か Mac が起動していれば機械学習も自動で進む
- PC が止まっていて失敗した分は、PC を起動したあと「ジョブ」画面で各ジョブの「**不足分**」（Missing）を押すと再実行される
- PC で常にコンテナを動かす必要はない。使わないときは `docker compose stop`、再開は `docker compose start`

## 更新 {#update}

ラズパイの Immich を更新したら、Windows PC・Mac も同じバージョンにそろえる（バージョンがずれると不具合の原因になる）。

```
cd <リポジトリ>\immich\remote-ml
docker compose pull
docker compose up -d
```

## セキュリティ {#security}

- 機械学習コンテナには**認証がない**。LAN の中から誰でも呼べるため、ルーターでポート 3003 を開けない
- ファイアウォールの許可はプライベートネットワークに限定する。カフェなどの公共 Wi-Fi にノート PC をつないでいるときはコンテナを止める
- 送られるのはプレビュー画像で、コンテナは受け取った画像を保存しない

## 止める・元に戻す

1. `immich/immich-config.json` の `machineLearning.enabled` を `false` に戻し、`docker compose up -d --force-recreate immich-server`
2. ラズパイの中継を止める: `sudo systemctl disable --now immich-ml-relay@primary immich-ml-relay@backup`
3. Windows PC と Mac で `docker compose down -v`（`-v` でモデルのキャッシュも消す）
4. 手順 2 でファイアウォールのルールを足した場合は `Remove-NetFirewallRule -DisplayName "Immich ML (LAN)"`

顔やスマート検索の結果は Immich の DB に残る。
