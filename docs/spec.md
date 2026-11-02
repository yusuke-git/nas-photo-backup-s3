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
- セットアップ手順: [導入手順 2. バックアップ](setup-backup.md)
- スクリプトの解説: [backup.sh の解説](backup-script.md)

## 8. 写真の閲覧（Immich） {#immich}

- ツール: Immich（Docker Compose、`immich/docker-compose.yml`）。公式構成からの変更点は [導入手順 3. Immich](setup-immich.md#diff-from-official) に記載
- バージョン: `.env` の `IMMICH_VERSION=v3`（v3 系に追従。メジャー更新は手動）
- 取り込み方: 外部ライブラリ。`/mnt/nas/photos` をコンテナの `/mnt/media/photos` に読み取り専用（`:ro` = read-only）でマウントする
  - Immich の画面で削除しても NAS の元写真は消えない
  - アルバム・お気に入りなどは Immich の DB にだけ保存される（NAS や S3 には入らない）
- 新しい写真の取り込み: 6 時間ごとの自動スキャン（ネットワーク共有ではファイル監視が動かないため）
- サーバー設定: `immich/immich-config.json` で Git 管理（画面からは変更できない）
  - 機械学習（顔認識・スマート検索）は無効。機械学習コンテナは `ml` profile にして既定では起動しない
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
- セットアップ手順: [導入手順 3. Immich](setup-immich.md)

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
- ラズパイのメモリ（4GB / 8GB）と、機械学習を有効にするかどうか
