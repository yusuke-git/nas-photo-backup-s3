# NAS 写真バックアップ

Buffalo LS220D2EE の写真を Raspberry Pi 4 経由で AWS S3 Glacier Deep Archive にバックアップし、同じラズパイで動かす Immich で閲覧する仕組みです。

## 全体像

```
[PC] --保存--> [NAS] --読み取り専用でマウント--> [ラズパイ] --毎晩、新しい写真だけ--> [S3 Deep Archive]
                                                    └─ Immich（PC・スマホから閲覧）
```

| 構成要素 | 役割 | 実装 |
|---|---|---|
| infra | S3 バケット、IAM ユーザー、予算アラート | `infra/`（Terraform） |
| backup | 毎晩、新しい写真を S3 に追加のみでコピー | `backup/backup.sh`（rclone） |
| Immich | NAS の写真を読み取り専用で取り込み、PC・スマホで閲覧 | `immich/docker-compose.yml`（Docker Compose） |

## 読む順番

| 目的 | 読むページ |
|---|---|
| 何をどう作ったかを知る | [仕様書](spec.md) |
| スクリプトで手早く組み立てる | [クイックスタート](quickstart.md)（`setup/` の 3 本のスクリプト） |
| ゼロから手順を追って組み立てる | [1. AWS](setup-aws.md) → [2. バックアップ](setup-backup.md) → [3. Immich](setup-immich.md) の順に進める |
| 設定ファイルやスクリプトの中身を知る | [Terraform の解説](infra.md)、[backup.sh の解説](backup-script.md) |
| 動かしたあとの見張り・トラブル対応 | [料金の見張りと設定変更](operations.md)、[セキュリティ点検](security.md) |
| いつ何をしたかを確認する | [構築記録](records.md) |
| Claude Code から AWS を扱う、このサイトを作り直す | [Agent Toolkit for AWS](setup-agent-toolkit.md)、[ドキュメントの生成](docs-build.md) |

分からない言葉（IAM、SSE-S3、state など）は [用語集](glossary.md) にまとめています。
