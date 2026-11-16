# 導入手順 5. イベントのアルバム

NAS のイベントフォルダ（`2026/1003_運動会` など）を、年の下 2 桁を付けたフォルダ名の Immich のアルバム（`261003_運動会`）に自動でまとめる。[見張りモード](#watch) を使うと、NAS に保存してから 1〜3 分でアルバムに入る。[導入手順 3. Immich](setup-immich.md) を済ませ、外部ライブラリのスキャンが終わってから行う。設計の理由は [仕様書の 8章](spec.md#event-tagger)、コードの説明は [event_tagger のリファレンス](reference/event_tagger.md) を参照。

## 何が起きるか {#behavior}

| NAS のフォルダ | 写真が入るアルバム（既定） |
|---|---|
| `2026/1003_運動会/` | `261003_運動会` |
| `2026/1003_運動会/RAW/`（サブフォルダ） | `261003_運動会`（親のイベントと同じ） |
| `2025/1227_日常/` | `251227_日常`（`EXCLUDE` で外せる） |
| `2025/1003_運動会/` と `2026/1003_運動会/`（別の年に同じ名前） | `251003_運動会` と `261003_運動会`（別のアルバム） |
| `2025/misc/`、`2025/1301_x/`（規則に合わない） | 作らない |
| `.webaxs` などの隠しフォルダ | 作らない |

- 何度実行しても同じ結果になる。入っている写真は入れ直さず、ログに「入っていた」件数として出る
- NAS のファイルにも Immich の DB にも直接は触らない。Immich の API を呼ぶだけ
- アルバムに足すだけで、アルバムから写真を外すことはしない。手で写真を足したアルバムもそのまま
- 同じ名前のアルバムが自分のアカウントにすでにあれば、新しく作らずにそれに足す（手で作ったアルバムでも同じ）
- アルバムの日付（表示される期間）は、Immich が中の写真の撮影日から決める

### タグも付けたいとき {#tags}

`MODE=both`（または `tag`）にすると、`イベント/2026/1003_運動会` のような階層タグも付く。Immich の「タグ」画面にツリーで並び、検索で人物・場所などとも組み合わせられる。既定（`MODE=album`）ではタグは付けない。

## 1. API キーを作る

1. 外部ライブラリの**所有者のアカウント**でログインする（アルバムはアカウントごとなので、別のアカウントのキーでは写真が見えない）。[見張りモード](#watch) も使う場合は、所有者が**管理者**である必要がある（スキャンを頼む API が管理者だけのため）。1 人で使っているなら、最初に作った管理者アカウントがそのまま両方に当たる
2. 「アカウント設定」→「API キー」→「新しい API キー」
3. 名前は `event-albums`。権限は次のものだけにチェックを入れる（すべての権限を付けない）

| 権限 | 使う API | 必要なとき |
|---|---|---|
| `folder.read` | `GET /view/folder/unique-paths`、`GET /view/folder` | いつも |
| `album.read` | `GET /albums` | いつも（既定の `MODE=album`） |
| `album.create` | `POST /albums` | いつも（既定の `MODE=album`） |
| `albumAsset.create` | `PUT /albums/{id}/assets` | いつも（既定の `MODE=album`） |
| `tag.read`、`tag.create`、`tag.asset` | `GET /tags`、`PUT /tags`、`PUT /tags/{id}/assets` | `MODE=tag` / `both` のときだけ |
| `tag.delete` | `DELETE /tags/{id}` | `MODE=tag` / `both` で `PRUNE=1` のときだけ |
| `library.read` | `GET /libraries` | 見張りモードのときだけ（`LIBRARY_ID` を書けば不要） |
| `library.update` | `POST /libraries/{id}/scan` | 見張りモードのときだけ。スキャンを頼む |
| `queue.read`、`job.read` | `GET /queues/library`（古い版は `GET /jobs`） | 見張りモードのときだけ。スキャンが終わったかを見る |

`library.update` はスキャンのほか、外部ライブラリの設定（取り込むフォルダなど）も変えられる権限。写真を消す権限（`asset.delete`）は付けないので、このキーで写真は消せない。元写真は読み取り専用のマウントなので、NAS の写真も消えない。

表示されたキーは一度しか見られないので、そのまま次の手順の設定ファイルに貼る。

## 2. 設定ファイル

```
sudo install -d -m 755 /etc/immich-event-tagger
sudo install -m 600 -o pi /opt/nas-photo-backup/immich/tagger/tagger.env.example /etc/immich-event-tagger/tagger.env
sudo nano /etc/immich-event-tagger/tagger.env      # IMMICH_API_KEY を貼る
```

| 変数 | 既定 | 意味 |
|---|---|---|
| `IMMICH_URL` | `http://localhost:2283` | Immich の URL |
| `IMMICH_API_KEY` | （必須） | 手順 1 のキー |
| `PHOTOS_ROOT` | `/mnt/media/photos` | 外部ライブラリのフォルダ（コンテナの中のパス） |
| `MODE` | `album` | `album` / `tag` / `both` |
| `ALBUM_FORMAT` | `{yy}{folder}` | アルバム名。`{year}` `{yy}`（年の下 2 桁）`{mmdd}` `{mm}` `{dd}` `{name}` `{folder}` を使える。例 `{year}{folder}` → `20261003_運動会`。年を入れないと、別の年の同じフォルダ名が 1 つのアルバムにまとまる |
| `TAG_FORMAT` | `イベント/{year}/{folder}` | タグ名（`MODE=tag` / `both` のとき） |
| `EXCLUDE` | （空） | 対象外にするイベント名の正規表現。例 `EXCLUDE='^日常$'`（`$` を使うときは `'` で囲む） |
| `YEARS` | （空 = すべて） | 対象の年。例 `2025,2026` |
| `PRUNE` | `0` | `1` で、イベントフォルダがなくなったタグを消す（タグを使うときだけ。[下の説明](#prune)） |
| `DRY_RUN` | `0` | `1` で書き込みをせず、することだけをログに出す |
| `NAS_PHOTOS_DIR` | `/mnt/nas/photos` | 見張りモードで更新時刻を見る、ラズパイから見た NAS の写真のフォルダ |
| `WATCH_INTERVAL` | `60` | 見張りモードで更新時刻を見る間隔（秒） |
| `SCAN_TIMEOUT` | `900` | 見張りモードで、スキャンが終わるのを待つ最長の秒数 |
| `LIBRARY_ID` | （空 = 自動） | 外部ライブラリの ID。空なら `PHOTOS_ROOT` を取り込んでいるライブラリを探す |
| `LOCK_FILE` | `/run/lock/immich-event-tagger.lock` | 全体の実行と見張りモードが同時に書き込まないための鍵のファイル |

`ALBUM_FORMAT` を途中で変えると、前の名前のアルバムは残り、新しい名前のアルバムが別にできる。いらなくなったら画面で消す。

## 3. 手で試す

まず `--dry-run` で、何が起きるかだけを見る。

```
cd /opt/nas-photo-backup/immich/tagger
set -a; . /etc/immich-event-tagger/tagger.env; set +a
python3 event_tagger.py --dry-run               # 全部の年
python3 event_tagger.py --dry-run --year 2026   # 2026 年だけ
python3 event_tagger.py --year 2026             # 2026 年だけ実際に作る
python3 event_tagger.py                         # 全部
```

| 引数 | 意味 |
|---|---|
| `--dry-run` | 書き込まない（`DRY_RUN=1` と同じ） |
| `--mode album\|tag\|both` | `MODE` を一時的に変える |
| `--year 2026` | その年だけ。複数回書ける |
| `--prune` | `PRUNE=1` と同じ（見張りモードでは使えない） |
| `--watch` | [見張りモード](#watch)。止めるまで動き続ける（`Ctrl+C` で止める） |
| `-v` | 規則に合わず飛ばしたフォルダもログに出す |

ログの最後の行が結果。

```
完了: タグ追加 0（付いていた 0）、アルバム追加 1520（入っていた 0、新規アルバム 85）、タグ削除 0、エラー 0
```

2 回目からは「アルバム追加」が新しい写真の分だけになり、残りは「入っていた」に入る。

終了コード: `0` 成功、`1` 一部の写真で失敗（ログに `失敗:` の行）、`2` Immich につながらない・API キーが違うなど。

## 4. 毎日自動で動かす

```
sudo cp /opt/nas-photo-backup/immich/tagger/systemd/immich-event-tagger.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now immich-event-tagger.timer
systemctl list-timers immich-event-tagger.timer    # 次の実行時刻
```

外部ライブラリの自動スキャン（6 時間ごと: 0 時・6 時・12 時・18 時）の 30 分後、1 日 4 回（0:30・6:30・12:30・18:30）動く。NAS に写真を入れてから、おおむね 6 時間半以内にアルバムに入る。一度にたくさんの写真を入れてスキャンが 30 分で終わらなかった分は、次の回で入る。

Immich には「取り込みが終わったら外のスクリプトを呼ぶ」しくみがないので、スキャンの時刻に合わせて動かしている。`immich-config.json` のスキャンの時刻（`library.scan.cronExpression`）を変えたら、`immich-event-tagger.timer` の `OnCalendar` も合わせて変える。

すぐに入れたいときは、Immich で「外部ライブラリ」→「スキャン」を押し、取り込みが終わってから次を実行する。

```
sudo systemctl start immich-event-tagger.service
journalctl -u immich-event-tagger.service -n 50    # ログを見る
```

## 5. ほぼリアルタイムにする（見張りモード） {#watch}

手順 4 だけだと、NAS に写真を入れてからアルバムに入るまで最大 6 時間半かかる。Immich の外部ライブラリは 6 時間ごとのスキャンでしか新しい写真を取り込まず、Immich 自身のフォルダ監視（`library.watch`）は NAS（SMB）では動かないため。見張りモードを動かすと、NAS に保存してからおおむね 1〜3 分でアルバムに入る。

### しくみ

1. 1 分ごとに、NAS の写真のフォルダ（`/mnt/nas/photos`）の下にあるフォルダの更新時刻を前回と比べる。フォルダに写真を足すと、そのフォルダの更新時刻が変わる。写真を 1 枚ずつ見ないので、見るのはフォルダの数（数百）だけ
2. 変わったフォルダがあれば、次の 1 分も見て、更新時刻が止まる（コピーが終わる）まで待つ
3. Immich に外部ライブラリのスキャンを頼み（画面の「スキャン」ボタンと同じ）、取り込みのジョブがなくなるまで待つ
4. 変わったフォルダの写真だけを、アルバムに入れる

変化がない間は、フォルダの更新時刻を見るだけで Immich には何も頼まない。手順 4 の 1 日 4 回の全体の実行は、取りこぼしの保険としてそのまま動かしておく（見張りモードが止まっていた間の変化や、スキャンが `SCAN_TIMEOUT` で終わらなかった分はそこで入る）。

### 動かす

先に手順 1 の表の「見張りモードのときだけ」の権限を API キーに足しておく（キーを作り直した場合は `tagger.env` も書き換える）。

```
cd /opt/nas-photo-backup/immich/tagger
set -a; . /etc/immich-event-tagger/tagger.env; set +a
python3 event_tagger.py --watch --dry-run          # スキャンを頼まずに、検出だけを試す。NAS に写真を入れてログを見る（Ctrl+C で止める）

sudo cp /opt/nas-photo-backup/immich/tagger/systemd/immich-event-watch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now immich-event-watch.service
journalctl -u immich-event-watch.service -f        # ログを見続ける
```

ログの流れ（写真を 1 つのフォルダに入れたとき）:

```
見張りを開始: フォルダ 412 件、60 秒ごと
変化を検出: 2 フォルダ（止まるまで待つ）
スキャンを依頼: ライブラリ 1b2c...
イベント 1 件、写真 35 枚（規則に合わないフォルダ 1 件）
完了: タグ追加 0（付いていた 0）、アルバム追加 35（入っていた 0、新規アルバム 1）、タグ削除 0、エラー 0
```

「規則に合わないフォルダ」は、新しいイベントフォルダを作ったときに更新時刻が変わる年フォルダ（`2026` など）で、写真は取りに行かない。

### 気をつけること

- 変化を見つけるたびに、外部ライブラリ全体のスキャンが走る。スキャンは NAS の全ファイルの一覧を取るので、写真が数万枚だと 1 回あたり数分かかり、その間は NAS とラズパイが少し忙しくなる。写真を入れたときだけなので、普段は気にしなくてよい
- 同じ名前のファイルを上書きしただけではフォルダの更新時刻が変わらないことがあり、その場合は 6 時間ごとのスキャンと全体の実行で反映される
- NAS がマウントされていない間は、ログに警告を出して待つ。マウントが戻った最初の 1 回は、前回と比べずに覚えるだけ
- 見張りモードと全体の実行は、鍵のファイル（`LOCK_FILE`）で同時に書き込まないようにしている。同じ名前のアルバムが 2 つできるのを防ぐため

## イベントフォルダの名前を変えたとき {#prune}

外部ライブラリでは写真はパスで区別されるので、フォルダの名前を変えると、Immich では「古いパスの写真が消えて、新しいパスの写真が増えた」扱いになる。新しい写真は次の実行で新しい名前のアルバムに入る。

- 古い名前のアルバムは自動では消さない（手で足した写真や共有の設定があるかもしれないため）。中身が空になったら画面で消す
- タグを使っている場合（`MODE=tag` / `both`）、`PRUNE=1`（または `--prune`）にすると、`イベント/` の下にあって今のどのイベントフォルダにも当たらない末端のタグを消す。途中の階層（`イベント/2026` など）は残す。`--year` で絞ったときはその年のタグだけ。最初は `--dry-run --prune` で確かめる

## 止める・元に戻す

```
sudo systemctl disable --now immich-event-tagger.timer
sudo systemctl disable --now immich-event-watch.service   # 見張りモードを使っていた場合
```

作ったアルバムは「アルバム」画面で消す（アルバムを消しても写真は消えない）。タグを付けていた場合は「タグ」画面で `イベント` を消すと、その下のタグごと消える。API キーは「アカウント設定」→「API キー」で消す。
