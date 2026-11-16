# NAS写真バックアップ 仕様書（v0.2 ドラフト）

このシステムが何を、なぜそう作っているかをまとめたページ。組み立て方は「導入手順」の各ページ、言葉の意味は [用語集](glossary.md) を参照。

## 1. 目的 {#purpose}

- Buffalo LS220D2EE に保存している家族写真を、災害対策として AWS S3 Glacier Deep Archive に自動バックアップする
- Raspberry Pi 4 で [Immich](https://immich.app/) を動かし、NAS の写真を PC やスマホから閲覧できるようにする
- S3 は「普段は見ない保険」とし、復元は NAS が失われたときだけを想定する

## 2. 構成 {#architecture}

```
[PC] --(SMB 手動保存)--> [NAS: LS220D2EE]
                              |
                  SMBマウント（読み取り専用）
                              v
                      [Raspberry Pi 4]
                        ├─ backup : rclone で夜間に S3 へ追加のみ同期
                        └─ Immich : Docker Compose（NAS を外部ライブラリとして読み取り専用で取り込む）
                              |                 ^
                              v                 | LAN / Tailscale
                 [AWS S3 ap-southeast-2 /   [PC・スマホ]
                  DEEP_ARCHIVE]
```

## 3. NAS のフォルダ規則 {#nas-folders}

```
/Photo/                      ← 元写真（ユーザーが PC から保存）。nas-pi は読み取りのみ
  2025/
    1203_誕生日/
      IMG_0001.jpg
/Thumbnail/                  ← Immich のサムネイル。nas-pi に読み書きを許可
```

- 年フォルダ: `YYYY`（4桁）
- イベントフォルダ: `MMDD_イベント名`（例 `1203_誕生日`）
- 対象ファイル: `.jpg` / `.jpeg`、RAW の `.cr2`、動画の `.mov`（大文字小文字を区別しない）
- 隠しフォルダ（`.` で始まるフォルダ）の中は対象外。Buffalo の WebAccess が各フォルダに作る `.webaxs/thumbnail/*.jpg` などのサムネイルをバックアップしないため
- 共有フォルダ名は `Photo` と `Thumbnail`（どちらも NAS のトップ。大文字小文字を区別する）
- NAS のユーザー `nas-pi` をラズパイ専用に作り、`Photo` は読み取りのみ、`Thumbnail` は読み書きを許可する。ほかの共有には権限を付けない

## 4. ラズパイからの NAS マウント {#nas-mount}

- `/etc/fstab` で CIFS マウントする

| NAS の共有 | ラズパイのマウント先 | モード |
|---|---|---|
| `Photo` | `/mnt/nas/photos` | 読み取り専用（read-only。fstab では `ro`） |
| `Thumbnail` | `/mnt/nas/thumbnail` | 読み書き（read-write。fstab では `rw`） |

- LS220D はファームウェアによって対応する SMB バージョンが違うため、まず `vers=2.0` で試し、つながらなければ `vers=1.0` にする
- 認証情報（`nas-pi`）は `/etc/nas-credentials`（権限 600）に置き、Git には入れない
- `Photo` は NAS 側の権限とマウントの両方で読み取り専用にする（誤って消すのを防ぐため）。backup と Immich の両方がこのマウントを使う
- `Thumbnail` は読み書きでマウントし、Immich のサムネイル置き場にする（[8章](#immich)）

## 5. S3 設計 {#s3}

| 項目 | 設定 |
|---|---|
| リージョン | ap-southeast-2（シドニー）。新しい AWS エクスペリエンスのプロジェクトのリージョンで、ほかのリージョンにはリソースを作れない |
| バケット名 | `<アカウント固有>-nas-photo-backup` |
| ストレージクラス | アップロード時に直接 `DEEP_ARCHIVE` |
| キー | `photos/2025/1203_誕生日/IMG_0001.jpg`（NAS のパスと同じ） |
| 暗号化 | SSE-S3（追加料金なし） |
| パブリックアクセス | すべてブロック |
| バージョニング | 有効。アクセスキーが漏れて上書きされても元の写真が古い版として残る（[セキュリティ点検の 1](security.md#versioning)）。rclone は上書きしないので普段は追加料金なし |
| ライフサイクル | 未完了のマルチパートアップロードを7日で削除 |

### 追加のみの運用 {#append-only}

- Deep Archive は180日以内の削除や上書きでも残り日数分が課金される
- そのため `rclone copy --immutable` を使い、削除や上書きを一切しない
  - NAS で消した写真は S3 に残る（保険として望ましい）
  - 同じ名前で中身が変わった写真はエラーとしてログに出し、上書きしない

## 6. IAM（最小権限） {#iam}

バックアップ専用の IAM ユーザー `nas-backup` を作り、次の権限だけを与える。削除権限は与えない。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::<bucket>"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
      "Resource": "arn:aws:s3:::<bucket>/*"
    }
  ]
}
```

アクセスキーはラズパイの rclone 設定（`~/.config/rclone/rclone.conf`、権限 600）にだけ保存する。

### 料金の暴走対策 {#cost-guard}

- 予算（月5ドル）の実績が100%に達したら、Budget Actions が `nas-backup` に書き込み拒否ポリシー（`nas-backup-deny-write`）を自動で付ける
- Cost Anomaly Detection で、サービスごとの課金が普段より1ドル以上増えたら毎日メールで通知する
- 管理者権限を奪われて EC2 などを起動される被害は止められないため、管理者は SSO＋MFA（FIDO2 セキュリティキーかパスキー）にし、アクセスキーを作らない
- 発動したときの対応は [料金の見張りと設定変更](operations.md#auto-stop)

### 構築方法 {#build}

バケット、IAM ユーザー、予算アラート（月5ドル）は Terraform（`infra/`）で作る。各リソースの説明は [Terraform の解説](infra.md)。アクセスキーは state に残さないよう CLI で発行する。手順は [導入手順 1. AWS](setup-aws.md)。

## 7. バックアップジョブ {#backup-job}

- ツール: rclone（S3 バックエンド、`storage_class = DEEP_ARCHIVE`）
- 実装: `backup/backup.sh`、設定は `/etc/nas-backup/backup.env`
- 実行: systemd timer（`backup/systemd/nas-backup.timer`）で毎日 02:00
- 主なオプション: `copy --immutable --size-only --s3-no-head`（削除・上書きなし、HEAD リクエストなし）
- NAS 未マウント時は終了コード1で中止、二重起動は flock で防止
- ログ: `/var/log/nas-backup/backup.log`（logrotate で週次、8世代）
- セットアップ手順: [導入手順 2. バックアップ](setup-backup.md)（スクリプト `setup/2-pi-backup.sh` でもできる。[クイックスタート](quickstart.md)）
- スクリプトの解説: [backup.sh の解説](backup-script.md)

## 8. 写真の閲覧（Immich） {#immich}

- ツール: Immich（Docker Compose、`immich/docker-compose.yml`）。公式構成からの変更点は [導入手順 3. Immich](setup-immich.md#diff-from-official) に記載
- バージョン: `.env` の `IMMICH_VERSION=v3`（v3 系に追従。メジャー更新は手動）
- 取り込み方: 外部ライブラリ。`/mnt/nas/photos` をコンテナの `/mnt/media/photos` に読み取り専用（`:ro` = read-only）でマウントする
  - Immich の画面で削除しても NAS の元写真は消えない
  - アルバム・お気に入りなどは Immich の DB にだけ保存される（NAS や S3 には入らない）
- 新しい写真の取り込み: 6 時間ごとの自動スキャン（ネットワーク共有ではファイル監視が動かないため）
- サーバー設定: `immich/immich-config.json` で Git 管理（画面からは変更できない）
  - 機械学習（顔検出・スマート検索・OCR）は有効。ただし処理は家の Windows PC の機械学習コンテナ（`immich/remote-ml/`）に任せ（Windows が止まっているときは Mac が予備で処理）、PC は固定 IP ではなく mDNS の名前（`.env` の `ML_PRIMARY_HOST` / `ML_BACKUP_HOST`）で探す。コンテナからは `.local` を引けないため、ラズパイ本体の中継（`immich/ml-relay/`、socat）を `host.docker.internal:3101` / `:3102` で呼ぶ。ラズパイの機械学習コンテナ（`ml` profile）は起動しない。PC が止まっている間は機械学習のジョブだけが失敗し、あとから「不足分」で再実行する。手順は [導入手順 4](setup-remote-ml.md)
  - ジョブの並列数を Pi4 向けに減らす
- データの置き場所（ラズパイのローカルディスク、USB SSD 推奨）
  - `/srv/immich/library`: 動画変換、DB の自動ダンプ（`backups/`）など
  - サムネイルだけは NAS の `Thumbnail`（`/mnt/nas/thumbnail`）をコンテナの `/data/thumbs` にマウントして置く。ラズパイのディスクを節約するため。消えても Immich の「ジョブ」で再生成できるので、S3 へのバックアップ対象にはしない
  - `/srv/immich/postgres`: PostgreSQL（ネットワーク共有には置けない）
- 起動順: `docker.service` に `RequiresMountsFor=/mnt/nas/photos /mnt/nas/thumbnail` を付け、NAS のマウント後に起動する（`immich/systemd/docker.service.d/wait-nas.conf`）
- ポート: 2283（HTTP）。ルーターでポート開放はしない
- 外部アクセス: Tailscale（自分の端末だけがつながる VPN）。HTTPS が必要なら `tailscale serve`
- スマホからの自動アップロードは使わない（写真が NAS に入らず S3 にもバックアップされないため）
- API: Immich 本体の API（[Immich API ドキュメント](https://api.immich.app/)）をそのまま使い、このリポジトリでは独自の API を持たない
- セットアップ手順: [導入手順 3. Immich](setup-immich.md)（スクリプト `setup/3-pi-immich.sh` でもできる）

### イベントのアルバム {#event-tagger}

- 目的: イベントフォルダ（`YYYY/MMDD_イベント名`、[3章](#nas-folders)）を、年の下 2 桁を付けたフォルダ名（`261003_運動会`）の Immich のアルバムにして、アルバム画面からイベントごとに見られるようにする
- 実装: `immich/tagger/event_tagger.py`（Python 3、標準ライブラリだけ）。設定は `/etc/immich-event-tagger/tagger.env`
- 実行場所: ラズパイの上（`python3`）。Immich には `http://localhost:2283` でつなぐ。Docker のコンテナは増やさない
- 実行: systemd timer（`immich/tagger/systemd/immich-event-tagger.timer`）で、外部ライブラリの自動スキャン（6 時間ごと）の 30 分後に 1 日 4 回（0:30・6:30・12:30・18:30）。Immich には取り込み直後に外部のスクリプトを呼ぶしくみがないため、スキャンの時刻に合わせる（v3 のワークフロー機能は Immich のプラグインしか動かせない）。手で何度実行してもよい
- 見張りモード（`--watch`、`immich/tagger/systemd/immich-event-watch.service`）: ほぼリアルタイムにアルバムへ入れるため、常に動かしておく
  - 1 分ごと（`WATCH_INTERVAL`）に、ラズパイから見た NAS の写真のフォルダ（`/mnt/nas/photos`、読み取り専用）の下の全フォルダの更新時刻を集めて前回と比べる。ファイルは 1 枚ずつ見ない
  - 変化があれば、更新時刻が 1 回分止まる（コピーが終わる）まで待ってから、`POST /libraries/{id}/scan` で外部ライブラリのスキャンを頼み、`GET /queues/library`（古い版は `GET /jobs`）でライブラリのジョブがなくなるまで待つ（最長 `SCAN_TIMEOUT` 秒）
  - そのあと、変わったフォルダだけを `GET /view/folder` で取り直してアルバムに入れる（差分の処理）
  - スキャンを頼む API は管理者だけなので、見張りモードの API キーは管理者（かつ外部ライブラリの所有者）のアカウントで作る
  - 全体の実行と見張りモードは `flock`（`LOCK_FILE`）で同時に書き込まない。同じ名前のアルバムが 2 つできるのを防ぐため
  - 見張りモードが止まっていた間の変化や、スキャンが時間内に終わらなかった分は、1 日 4 回の全体の実行で入る
- 付け方
  - 既定はアルバム（`MODE=album`）。名前は年の下 2 桁＋フォルダ名（`2026/1003_運動会` → `261003_運動会`、`ALBUM_FORMAT={yy}{folder}`）。別の年に同じフォルダ名があってもアルバムが分かれる。サブフォルダの写真は親のイベントのアルバムに入る
  - 同じ名前のアルバムが自分のアカウントにあればそれに足す。アルバムには足すだけで、外さない。アルバムは自動では消さない
  - 設定（`MODE=tag` / `both`）でタグ `イベント/{年}/{MMDD_イベント名}`（`/` で階層になる）も付けられる。タグはいったん既定にしたが、見づらいため既定をアルバムに変えた
  - 規則に合わないフォルダ・隠しフォルダ・ゴミ箱の写真は対象外。`EXCLUDE` で特定のイベント名（`日常` など）を外せる
  - ファイル名は Unicode の NFC にそろえて比べる（NAS 経由で濁点が分かれていても同じアルバムになる）
- 冪等: 入っている写真・付いているタグは Immich が `duplicate` を返すので、件数だけ数える。新しい写真の分だけが増える
- 名前の変更: 外部ライブラリでは写真はパスで区別されるため、フォルダ名を変えると新しい名前のアルバムが新しくできる。古いアルバムは手で消す。タグを使うときは、古いタグを `PRUNE=1` のときだけ消す（`イベント/` の下の末端のタグに限る）
- 使う Immich API（v2 から安定版のものだけ）

| API | 権限 | 用途 |
|---|---|---|
| `GET /view/folder/unique-paths` | `folder.read` | 写真があるフォルダの一覧 |
| `GET /view/folder?path=` | `folder.read` | フォルダ直下の写真 |
| `GET /albums`、`POST /albums`、`PUT /albums/{id}/assets` | `album.read`、`album.create`、`albumAsset.create` | アルバムの一覧・作成・写真の追加（既定） |
| `GET /tags`、`PUT /tags` | `tag.read`、`tag.create` | タグの一覧と作成（`MODE=tag` / `both` のとき） |
| `PUT /tags/{id}/assets` | `tag.asset` | 写真にタグを付ける（`MODE=tag` / `both` のとき） |
| `DELETE /tags/{id}` | `tag.delete` | 古いタグを消す（`MODE=tag` / `both` で `PRUNE=1` のとき） |
| `GET /libraries` | `library.read` | 外部ライブラリの ID を探す（見張りモード、`LIBRARY_ID` が空のとき。管理者だけ） |
| `POST /libraries/{id}/scan` | `library.update` | スキャンを頼む（見張りモード。管理者だけ） |
| `GET /queues/library`、`GET /jobs` | `queue.read`、`job.read` | スキャンの終わりを待つ（見張りモード。管理者だけ） |

- API キー: 外部ライブラリの所有者のアカウントで、上の権限だけを付けて作る。`tagger.env`（権限 600）にだけ置き、Git には入れない
- AWS は使わない（追加料金なし）
- セットアップ手順: [導入手順 5. イベントのアルバム](setup-event-tagger.md)

## 9. 廃止した構成要素 {#removed}

自作のサムネイル生成（thumbgen）と LAN 内 WebApp（webapp）は Immich に置き換えたため削除した（PR #2、#3 で追加したもの。Git の履歴から復元できる）。ラズパイで動かしていた場合は次で止める。

```
sudo systemctl disable --now nas-thumbgen.timer nas-webapp.service
sudo rm /etc/systemd/system/nas-thumbgen.* /etc/systemd/system/nas-webapp.service
sudo systemctl daemon-reload
sudo umount /mnt/nas/thumbnails   # /etc/fstab の thumbnails の行も消す
```

## 10. 費用見積もり（概算、着手前に最新の料金表で再確認） {#cost}

シドニー（ap-southeast-2）の料金で計算（AWS 公開料金表 2026-10-15 版）。

| 項目 | 100GB | 2TB |
|---|---|---|
| 保管料（月） | 約0.2ドル | 約4ドル |
| 初回アップロード（リクエスト料金、1回だけ） | 約1〜2ドル | 約20〜30ドル |
| 全部を復元（取り出しと転送、1回あたり） | 約15ドル | 約250ドル |

- 1枚5MBとして計算（100GB で約2万枚、2TB で約40万枚）
- 使った単価（シドニー）
  - 保管: 0.002ドル/GB・月
  - アップロード: PUT 1,000件あたり0.06ドル
  - 復元（大量取り出し・Bulk）: 0.005ドル/GB と 1,000件あたり0.03ドル
  - インターネットへの転送: 0.114ドル/GB（全リージョン合計で月100GBまでは無料。表には含めていない）
- 東京（ap-northeast-1）と比べると、保管料と転送料は同じ。PUT はやや安く（0.065→0.06ドル）、Bulk 取り出しのリクエストはやや高い（0.025→0.03ドル）。合計はほぼ変わらない
- 費用の大半は転送料なので、復元は一度にまとめず、月100GBの無料枠に収まるように分けると安くなる
- 復元には12〜48時間かかる
- 1オブジェクトにつき約40KBの管理用データが追加で課金されるが、この規模なら影響は小さい

## 11. 未決事項 {#open-issues}

- NAS の SMB バージョン（`vers=2.0` で試す）
- バックアップ失敗時の通知方法（メール、LINE など）
- Immich の DB の自動ダンプ（`/srv/immich/library/backups/`）を NAS や S3 にも送るか（S3 に送る場合は少額だが追加料金がかかるため、送る前に確認する）
- ラズパイのメモリ（4GB / 8GB）。機械学習は Windows PC に任せることにした（[導入手順 4](setup-remote-ml.md)）。常時動かしたくなったら、Intel N100 系ミニPC（OpenVINO 対応）への置き換えを検討する
