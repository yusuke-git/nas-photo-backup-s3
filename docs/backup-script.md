# backup.sh の解説

`backup/backup.sh` が何をしているかを、上から順に説明する。設定と使い方は [導入手順 2. バックアップ](setup-backup.md)、設計の理由は [仕様書の 5〜7章](spec.md#s3) を参照。

## rclone とは {#rclone}

[rclone](https://rclone.org/) は、ファイルをクラウドストレージとやり取りするためのコマンドラインツール（オープンソース、無料）。「クラウド版の rsync」と呼ばれ、S3、Google ドライブ、OneDrive など 70 種類以上の保存先に同じ書き方で対応している。

- 保存先の情報（種類、キー、リージョンなど）は `~/.config/rclone/rclone.conf` に「リモート」として名前を付けて書いておく。このプロジェクトでは `[s3backup]` という名前
- コマンドでは `リモート名:バケット/フォルダ` の形で保存先を指す。`s3backup:example-nas-photo-backup/photos` は「`s3backup` の設定で、バケット `example-nas-photo-backup` の `photos/` の下」という意味
- 主なコマンド: `copy`（足りないものを送る）、`sync`（先を元と同じにする。先にしかないものは消す）、`ls` / `lsd`（一覧）など。このプロジェクトは消さない `copy` だけを使う

AWS CLI（`aws s3 cp` など）でも送れるが、rclone は「どれがまだ送っていないか」の比較、フィルター、ログ、Deep Archive への直接保存を 1 コマンドでまとめてできるので採用している。

## 全体の流れ

```
backup.env を読む
  → 二重起動していないか確認（flock）
  → NAS がマウントされているか確認
  → rclone copy で NAS → S3 に「新しいファイルだけ」を追加
```

画面には何も出さず、結果はすべて `/var/log/nas-backup/backup.log` に書く。正常に終われば終了コード 0。

## 1. 安全装置（4行目）

```bash
set -euo pipefail
```

| オプション | 意味 |
|---|---|
| `-e` | どこかのコマンドが失敗したら、その場で止まる |
| `-u` | 未定義の変数を使ったらエラーにする（変数名の打ち間違いで空の値のまま動くのを防ぐ） |
| `-o pipefail` | `a \| b` のようにつないだコマンドの途中で失敗しても、失敗として扱う |

## 2. 設定の読み込み（6〜17行目）

```bash
CONF_FILE="${CONF_FILE:-/etc/nas-backup/backup.env}"
ENV_DRY_RUN="${DRY_RUN:-}"
[ -f "$CONF_FILE" ] && . "$CONF_FILE"
[ -n "$ENV_DRY_RUN" ] && DRY_RUN="$ENV_DRY_RUN"
```

- `/etc/nas-backup/backup.env` があれば読み込む（`.` は「このファイルの中身をここで実行する」の意味）
- コマンドラインで `DRY_RUN=1 backup.sh` と指定した場合は、`backup.env` の `DRY_RUN` よりそちらを優先する。読み込む前に退避しておき、読み込んだ後で戻している（PR #13 で修正）

続く部分で、`backup.env` に書かれていない値に既定値を入れる。

| 変数 | 既定値 | 意味 |
|---|---|---|
| `SRC` | `/mnt/nas/photos` | バックアップ元（NAS の `Photo` のマウント先） |
| `DEST` | なし（必須） | バックアップ先。未設定ならメッセージを出して止まる（`${DEST:?...}`） |
| `LOG_DIR` | `/var/log/nas-backup` | ログの置き場所 |
| `LOCK_FILE` | `/run/lock/nas-backup.lock` | 二重起動を防ぐための目印のファイル |
| `DRY_RUN` | `0` | `1` なら試運転（何も送らない） |

`${変数:-値}` は「変数が空なら値を使う」という書き方。

## 3. 二重起動の防止（19〜24行目）

```bash
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "別のバックアップが実行中のため終了します" >&2
  exit 0
fi
```

- ロックファイルを開いて `flock` で鍵をかける。鍵はスクリプトが終わると自動で外れる
- 初回のアップロードは何時間もかかることがあり、その間に翌日 02:00 のタイマーが来ても、2つ目は何もせずに終わる（同じファイルを同時に送って料金が二重になるのを防ぐ）

## 4. NAS のマウント確認（26〜30行目）

```bash
if ! mountpoint -q "$SRC" && ! mountpoint -q "$(dirname "$SRC")"; then
  echo "NAS がマウントされていません: $SRC" >&2
  exit 1
fi
```

NAS が落ちていてマウントされていないと、`/mnt/nas/photos` はラズパイ上のただの空フォルダになる。その状態で動いても害はない（追加のみなので S3 から消えることはない）が、失敗に気づけるよう終了コード 1 で止める。

## 5. rclone の実行（32〜49行目）

```bash
rclone copy "$SRC" "$DEST" [オプション...]
```

`copy` は「元にあって先にないファイルを送る」動作。`sync` と違い、元で消したファイルを先から消すことはない。

| オプション | 意味 | 理由 |
|---|---|---|
| `--immutable` | 同じ名前で中身が違うファイルは、上書きせずエラーとしてログに出す | Deep Archive は上書きでも 180 日分課金されるため、上書きは一切しない |
| `--size-only` | 同じファイルかどうかを、サイズだけで判断する | 更新日時を調べるには 1 ファイルごとに HEAD リクエストが要り、料金がかかるため |
| `--s3-no-head` | アップロード後の確認リクエストを省く | 同上 |
| `--filter "- .*/**"` | `.` で始まるフォルダの中は対象外 | Buffalo の WebAccess が作る `.webaxs/thumbnail/` などの自動サムネイルを送らない（PR #14） |
| `--filter "+ *.{jpg,jpeg,JPG,JPEG,cr2,CR2,mov,MOV}"` | JPEG・RAW（CR2）・動画（MOV）を対象にする | 元写真だけを送る（PR #15） |
| `--filter "- *"` | それ以外はすべて対象外 | `.DS_Store` や `.appthumb` などを送らない |
| `--transfers 2` | 同時に 2 ファイルずつ送る | ラズパイと家の回線に負担をかけすぎない |
| `--log-file` / `--log-level INFO` | ログをファイルに、送ったファイル名まで書く | 何を送ったか後から確認できるように |
| `--stats-one-line --stats 0` | 途中経過の表示を出さず、最後に 1 行で集計を出す | ログを読みやすくする |

`--filter` は上から順に判定され、最初に当てはまったルールで決まる。たとえば `2025/1203_誕生日/.webaxs/thumbnail/IMG_0001.JPG.M.jpg` は 1 つ目の `- .*/**` に当てはまるので、`.jpg` でも対象外になる。

`DRY_RUN=1` のときは最後に `--dry-run` が付き、送るはずのファイルを `Skipped copy as --dry-run is set` としてログに書くだけになる。

## bash の書き方（args 配列と展開）

### `${...}` の展開

| 書き方 | 意味 | 例 |
|---|---|---|
| `${SRC:-/mnt/nas/photos}` | `SRC` が空なら右の値を使う | `backup.env` に書いていなければ既定値になる |
| `${DEST:?メッセージ}` | `DEST` が空ならメッセージを出してスクリプトを止める | 送り先の書き忘れで動いてしまうのを防ぐ |
| `$(dirname "$SRC")` | カッコ内のコマンドを実行し、その出力に置き換える | `/mnt/nas/photos` → `/mnt/nas` |
| `"$SRC"` | 変数を 1 つの値として渡す（`"` で囲む） | 値に空白があっても分割されない |

### args 配列

```bash
args=(
  copy "$SRC" "$DEST"
  --immutable
  ...
)
[ "$DRY_RUN" = "1" ] && args+=(--dry-run)
rclone "${args[@]}"
```

- `args=( ... )` は bash の「配列」。カッコの中に空白や改行で区切って並べた 1 つ 1 つが要素になる。上の例なら `args[0]` が `copy`、`args[1]` が `/mnt/nas/photos`、`args[2]` が `s3backup:example-nas-photo-backup/photos`、…
- 配列の中でも `#` から行末まではコメントとして無視される。オプションごとに説明を書けるのが配列にした理由の 1 つ
- `args+=(--dry-run)` は配列の最後に要素を足す。`[ 条件 ] && 処理` は「条件が成り立つときだけ処理する」の短い書き方なので、`DRY_RUN=1` のときだけ `--dry-run` が付く
- `"${args[@]}"` は「配列の要素を 1 つずつ、別々の引数として並べる」展開。最終的に実行されるのは次と同じ:

```bash
rclone copy /mnt/nas/photos s3backup:example-nas-photo-backup/photos --immutable --size-only --s3-no-head \
  --filter "- .*/**" --filter "+ *.{jpg,jpeg,JPG,JPEG,cr2,CR2,mov,MOV}" --filter "- *" \
  --transfers 2 --log-file /var/log/nas-backup/backup.log --log-level INFO --stats-one-line --stats 0 [--dry-run]
```

1 本の文字列（`ARGS="copy $SRC ..."`）にしないのは、空白を含む値（例: `- .*/**`）や `*` が bash に分割・展開されて壊れるため。配列で `"${args[@]}"` と書けば、各要素がそのままの形で rclone に渡る。

### `{jpg,JPG,...}` は誰が解釈するか

`"+ *.{jpg,jpeg,...}"` は `"` で囲んであるので、bash はそのまま文字列として rclone に渡す（bash の `{a,b}` 展開や `*` の展開は起きない）。`{...}` と `*` を解釈するのは rclone 側のフィルター機能で、「`.jpg` か `.jpeg` か … で終わるファイル」という意味になる。

## rclone copy の中で起きていること

1. **元の一覧を作る**: `/mnt/nas/photos` の下を全部たどり、ファイル名とサイズを集める。このときフィルターで対象外のもの（隠しフォルダ、対象外の拡張子）を落とす
2. **先の一覧を作る**: S3 に `ListObjectsV2` を送り、`photos/` 以下のオブジェクト名とサイズを集める（1 回で最大 1,000 件。2 万件なら約 20 回で、料金は 1 円未満）
3. **突き合わせる**: 同じパス（例: `2026/1003_x/IMG_0001.JPG` と `photos/2026/1003_x/IMG_0001.JPG`）同士を比べる
    - 先にない → 送る対象
    - 先にあってサイズが同じ → 何もしない（`--size-only`）
    - 先にあってサイズが違う → `--immutable` により上書きせずエラーをログに出す
4. **送る**: 2 ファイルずつ並行して（`--transfers 2`）アップロードする
    - 200MiB 未満のファイルは 1 回の `PutObject` で送る。ファイルの MD5 を一緒に送り、S3 側で中身が壊れていないか検証される
    - それ以上（動画など）はマルチパートアップロードで小分けにして送る。途中で止まった断片は、S3 のライフサイクル設定で 7 日後に自動削除される（[Terraform の解説の s3.tf](infra.md#s3)）
    - `rclone.conf` の設定により、送るときに「保存クラス = DEEP_ARCHIVE」「暗号化 = AES256」を指定する。いったん Standard に置いてから移すのではなく、最初から Deep Archive に入る
5. **記録する**: 送ったファイルを `Copied (new)` としてログに書き、最後に件数と量の集計を 1 行出す

`--dry-run` のときは 1〜3 までを行い、4 の代わりに「送るはずだった」とログに書く。S3 に送るのは 2 の一覧取得だけなので、料金はほぼかからない。

## ログの読み方

| ログの例 | 意味 |
|---|---|
| `INFO : 2026/1003_x/IMG_0001.JPG: Copied (new)` | アップロードした |
| `NOTICE: ...: Skipped copy as --dry-run is set` | 試運転で、本番ならアップロードするファイル |
| `ERROR : ...: ... immutable ...` | 同じ名前で中身が違うファイルがある。上書きしていない |
| `There was nothing to transfer` | 新しいファイルがなかった |

## 実行のされ方

- 手動: `/opt/nas-photo-backup/backup/backup.sh`（`pi` ユーザーで。`sudo` は付けない。rclone のキーが `pi` のホームにあるため）
- 自動: `backup/systemd/nas-backup.timer` が毎日 02:00（最大 10 分ずらす）に `nas-backup.service` を起動し、`pi` ユーザーで実行する。CPU とディスクの優先度を下げて（`Nice=10`、`IOSchedulingClass=idle`）、Immich など他の処理の邪魔をしない。ラズパイの電源が切れていて 02:00 を逃した場合は、次に起動したときに実行する（`Persistent=true`）
