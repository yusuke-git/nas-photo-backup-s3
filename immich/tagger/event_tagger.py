#!/usr/bin/env python3
"""NAS のイベントフォルダを、年付きのフォルダ名の Immich のアルバムにする。

NAS の写真は ``YYYY/MMDD_イベント名/`` に並んでいる（仕様書 3章）。Immich の
外部ライブラリに取り込まれた写真のパスからイベントを取り出し、
``261003_運動会`` のように「年の下 2 桁＋フォルダ名」のアルバムに入れる。
設定（``MODE=tag`` / ``both``）で ``イベント/2026/1003_運動会`` のような階層タグも付けられる。

- Immich の API（``x-api-key``）だけを使い、NAS のファイルや Immich の DB には触らない
- 何度実行しても同じ結果になる（冪等）。入っている写真は入れ直さず、件数だけ数える
- 標準ライブラリだけで動く（ラズパイの ``python3`` にそのまま置ける）
- ``--watch`` で見張りモードになる。NAS のフォルダの更新時刻を 1 分ごとに見て、
  変わったら Immich に外部ライブラリのスキャンを頼み、変わったフォルダの写真だけをアルバムに入れる

使い方は ``docs/setup-event-tagger.md`` を参照。
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

log = logging.getLogger("event_tagger")

DEFAULT_TAG_FORMAT = "イベント/{year}/{folder}"
# 年の下 2 桁を付けて、別の年に同じフォルダ名があってもアルバムが分かれるようにする（例 261003_運動会）
DEFAULT_ALBUM_FORMAT = "{yy}{folder}"
DEFAULT_PHOTOS_ROOT = "/mnt/media/photos"
CHUNK = 500  # 1 リクエストで送るアセット ID の数
DEFAULT_NAS_PHOTOS_DIR = "/mnt/nas/photos"
DEFAULT_LOCK_FILE = "/run/lock/immich-event-tagger.lock"

_YEAR_RE = re.compile(r"^\d{4}$")
_EVENT_RE = re.compile(r"^(\d{2})(\d{2})_(.+)$")


@dataclass(frozen=True)
class Event:
    """イベントフォルダ 1 つ分の情報。

    Attributes:
        year: 年フォルダ（例 ``"2026"``）。
        mmdd: 月日（例 ``"1003"``）。
        name: イベント名（例 ``"運動会"``）。
    """

    year: str
    mmdd: str
    name: str

    @property
    def folder(self) -> str:
        """イベントフォルダの名前（例 ``"1003_運動会"``）。"""
        return f"{self.mmdd}_{self.name}"

    def format(self, template: str) -> str:
        """テンプレートにイベントの値を入れる。

        Args:
            template: ``{year}`` ``{yy}``（年の下 2 桁）``{mmdd}`` ``{mm}`` ``{dd}`` ``{name}`` ``{folder}`` を使える文字列。

        Returns:
            値を入れた文字列。
        """
        return template.format(
            year=self.year,
            yy=self.year[-2:],
            mmdd=self.mmdd,
            mm=self.mmdd[:2],
            dd=self.mmdd[2:],
            name=self.name,
            folder=self.folder,
        )


def nfc(text: str) -> str:
    """Unicode を NFC にそろえる（NAS 経由のファイル名は濁点が分かれていることがあるため）。"""
    return unicodedata.normalize("NFC", text)


def parse_event(folder_path: str, root: str) -> Event | None:
    """フォルダのパスからイベントを取り出す。

    ``<root>/YYYY/MMDD_イベント名`` とその下のサブフォルダがイベントになる。
    それ以外（年フォルダの直下、規則に合わない名前、隠しフォルダ）は ``None``。

    Args:
        folder_path: Immich が持つフォルダのパス（コンテナの中のパス）。
        root: 外部ライブラリのフォルダ（例 ``/mnt/media/photos``）。

    Returns:
        イベント。対象外なら ``None``。
    """
    root = root.rstrip("/")
    path = nfc(folder_path).rstrip("/")
    if not path.startswith(root + "/"):
        return None
    parts = path[len(root) + 1 :].split("/")
    if len(parts) < 2 or any(p.startswith(".") for p in parts):
        return None
    year, folder = parts[0], parts[1]
    if not _YEAR_RE.match(year):
        return None
    m = _EVENT_RE.match(folder)
    if not m:
        return None
    mm, dd, name = m.group(1), m.group(2), m.group(3).strip()
    if not (1 <= int(mm) <= 12 and 1 <= int(dd) <= 31) or not name:
        return None
    return Event(year=year, mmdd=mm + dd, name=name)


class ImmichError(RuntimeError):
    """Immich の API がエラーを返した。"""


class ImmichClient:
    """Immich API の必要な部分だけを呼ぶ小さなクライアント。

    Args:
        base_url: Immich の URL（例 ``http://localhost:2283``）。``/api`` は付けなくてよい。
        api_key: Immich の API キー。
        timeout: 1 リクエストのタイムアウト秒。
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 60) -> None:
        base = base_url.rstrip("/")
        self.base = base if base.endswith("/api") else base + "/api"
        self.api_key = api_key
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any = None, query: dict | None = None) -> Any:
        """API を呼んで JSON を返す。

        Raises:
            ImmichError: HTTP エラーや接続エラーのとき。
        """
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("x-api-key", self.api_key)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                raw = res.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise ImmichError(f"{method} {path}: HTTP {e.code} {detail}") from e
        except urllib.error.URLError as e:
            raise ImmichError(f"{method} {path}: {e.reason}") from e
        return json.loads(raw) if raw else None

    def unique_paths(self) -> list[str]:
        """写真があるフォルダの一覧（``GET /view/folder/unique-paths``）。"""
        return self.request("GET", "/view/folder/unique-paths")

    def folder_assets(self, path: str) -> list[dict]:
        """フォルダ直下の写真（``GET /view/folder``）。"""
        return self.request("GET", "/view/folder", query={"path": path})

    def tags(self) -> list[dict]:
        """自分のタグの一覧（``GET /tags``）。"""
        return self.request("GET", "/tags")

    def upsert_tags(self, values: list[str]) -> list[dict]:
        """タグを作る。あれば既存のものを返す（``PUT /tags``）。``/`` で階層になる。"""
        return self.request("PUT", "/tags", {"tags": values})

    def tag_assets(self, tag_id: str, asset_ids: list[str]) -> list[dict]:
        """写真にタグを付ける（``PUT /tags/{id}/assets``）。付いていれば ``duplicate``。"""
        return self.request("PUT", f"/tags/{tag_id}/assets", {"ids": asset_ids})

    def delete_tag(self, tag_id: str) -> None:
        """タグを消す（``DELETE /tags/{id}``）。写真は消えない。"""
        self.request("DELETE", f"/tags/{tag_id}")

    def libraries(self) -> list[dict]:
        """外部ライブラリの一覧（``GET /libraries``、管理者だけ）。"""
        return self.request("GET", "/libraries")

    def scan_library(self, library_id: str) -> None:
        """外部ライブラリのスキャンを頼む（``POST /libraries/{id}/scan``、管理者だけ）。"""
        self.request("POST", f"/libraries/{library_id}/scan")

    def library_queue_busy(self) -> bool:
        """ライブラリのジョブ（スキャンと取り込み）が残っているか。

        ``GET /queues/library``（v2.4 から）を使い、ない版では ``GET /jobs`` を使う。どちらも管理者だけ。
        """
        try:
            st = self.request("GET", "/queues/library")["statistics"]
        except ImmichError as e:
            if "HTTP 404" not in str(e):
                raise
            st = self.request("GET", "/jobs")["library"]["jobCounts"]
        return any(st.get(k, 0) for k in ("active", "waiting", "delayed"))

    def albums(self) -> list[dict]:
        """自分が持っているアルバムの一覧（``GET /albums?isOwned=true``）。"""
        return self.request("GET", "/albums", query={"isOwned": "true"})

    def create_album(self, name: str, asset_ids: list[str]) -> dict:
        """アルバムを作る（``POST /albums``）。"""
        return self.request("POST", "/albums", {"albumName": name, "assetIds": asset_ids})

    def add_album_assets(self, album_id: str, asset_ids: list[str]) -> list[dict]:
        """アルバムに写真を足す（``PUT /albums/{id}/assets``）。入っていれば ``duplicate``。"""
        return self.request("PUT", f"/albums/{album_id}/assets", {"ids": asset_ids})


@dataclass
class Config:
    """実行の設定。環境変数とコマンドラインの引数から作る。

    Attributes:
        url: Immich の URL。
        api_key: Immich の API キー。
        root: 外部ライブラリのフォルダ（コンテナの中のパス）。
        mode: ``album``（既定）、``tag``、``both`` のどれか。
        tag_format: タグ名のテンプレート。
        album_format: アルバム名のテンプレート。
        exclude: このパターンに合うイベント名は対象外（正規表現。空なら除外なし）。
        years: 対象の年（空ならすべて）。
        prune: イベントフォルダがなくなったタグを消すか。
        dry_run: 書き込みをせずに、するはずだったことをログに出すか。
        nas_dir: ラズパイから見た NAS の写真のフォルダ（見張りモードで更新時刻を見る場所）。
        watch_interval: 見張りモードで更新時刻を見る間隔（秒）。
        scan_timeout: 見張りモードで、スキャンの終わりを待つ最長の秒数。
        library_id: 外部ライブラリの ID。空なら ``root`` を取り込んでいるライブラリを探す。
        lock_file: 全体の実行と見張りモードが同時に書き込まないための鍵のファイル。
        watch: 見張りモードで動くか。
    """

    url: str
    api_key: str
    root: str = DEFAULT_PHOTOS_ROOT
    mode: str = "album"
    tag_format: str = DEFAULT_TAG_FORMAT
    album_format: str = DEFAULT_ALBUM_FORMAT
    exclude: str = ""
    years: set[str] = field(default_factory=set)
    prune: bool = False
    dry_run: bool = False
    nas_dir: str = DEFAULT_NAS_PHOTOS_DIR
    watch_interval: float = 60
    scan_timeout: float = 900
    library_id: str = ""
    lock_file: str = DEFAULT_LOCK_FILE
    watch: bool = False


@dataclass
class Stats:
    """実行結果の件数。"""

    events: int = 0
    assets: int = 0
    tagged: int = 0
    already_tagged: int = 0
    album_added: int = 0
    already_in_album: int = 0
    albums_created: int = 0
    tags_deleted: int = 0
    skipped_folders: int = 0
    errors: int = 0


def _chunks(items: list[str], size: int = CHUNK) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _count(results: list[dict], stats: Stats, added: str, already: str) -> None:
    for r in results:
        if r.get("success"):
            setattr(stats, added, getattr(stats, added) + 1)
        elif r.get("error") == "duplicate":
            setattr(stats, already, getattr(stats, already) + 1)
        else:
            stats.errors += 1
            log.warning("失敗: asset=%s error=%s %s", r.get("id"), r.get("error"), r.get("errorMessage", ""))


def collect_events(
    client: ImmichClient, cfg: Config, stats: Stats, paths: Iterable[str] | None = None
) -> dict[Event, list[str]]:
    """フォルダの一覧からイベントごとの写真 ID を集める。

    Args:
        client: Immich のクライアント。
        cfg: 設定。
        stats: 件数を足していく先。
        paths: 調べるフォルダ（コンテナの中のパス）。省略時は Immich にあるすべてのフォルダ。

    Returns:
        イベントと、そのフォルダ（サブフォルダを含む）にある写真 ID の対応。
    """
    exclude = re.compile(cfg.exclude) if cfg.exclude else None
    events: dict[Event, list[str]] = {}
    for path in sorted(client.unique_paths() if paths is None else paths):
        event = parse_event(path, cfg.root)
        if event is None:
            if nfc(path).rstrip("/").startswith(cfg.root.rstrip("/") + "/"):
                log.debug("対象外のフォルダ: %s", path)
                stats.skipped_folders += 1
            continue
        if cfg.years and event.year not in cfg.years:
            continue
        if exclude and exclude.search(event.name):
            log.debug("除外: %s", path)
            continue
        ids = [a["id"] for a in client.folder_assets(path) if not a.get("isTrashed")]
        events.setdefault(event, []).extend(ids)
    return events


def apply_tags(client: ImmichClient, cfg: Config, events: dict[Event, list[str]], stats: Stats) -> None:
    """イベントごとのタグを作り、写真に付ける。``prune`` なら古いタグを消す。"""
    by_value = {nfc(t["value"]): t for t in client.tags()}
    wanted = {ev: nfc(ev.format(cfg.tag_format)) for ev in events}

    missing = sorted({v for v in wanted.values() if v not in by_value})
    if missing:
        log.info("新しいタグ: %d 件", len(missing))
        for v in missing:
            log.info("  + タグ %s", v)
        if not cfg.dry_run:
            for part in _chunks(missing, 100):
                for t in client.upsert_tags(part):
                    by_value[nfc(t["value"])] = t

    for ev, ids in sorted(events.items(), key=lambda kv: (kv[0].year, kv[0].mmdd, kv[0].name)):
        value = wanted[ev]
        tag = by_value.get(value)
        if cfg.dry_run:
            log.info("[dry-run] %s に %d 枚", value, len(ids))
            continue
        if tag is None:
            stats.errors += 1
            log.error("タグを作れなかった: %s", value)
            continue
        before = stats.tagged
        for part in _chunks(ids):
            _count(client.tag_assets(tag["id"], part), stats, "tagged", "already_tagged")
        if stats.tagged > before:
            log.info("%s に %d 枚を追加", value, stats.tagged - before)

    if cfg.prune:
        prune_tags(client, cfg, set(wanted.values()), by_value, stats)


def _managed_prefix(tag_format: str) -> str:
    """タグのテンプレートのうち、イベントによらない先頭部分（例 ``イベント/``）。"""
    head = tag_format.split("{", 1)[0]
    return head[: head.rfind("/") + 1] if "/" in head else ""


def prune_tags(
    client: ImmichClient, cfg: Config, wanted: set[str], by_value: dict[str, dict], stats: Stats
) -> None:
    """イベントフォルダがなくなった（名前を変えた・消した）タグを消す。

    消すのは、テンプレートの先頭部分（既定では ``イベント/``）の下で、今回のイベントの
    どれにも当たらない「末端」のタグだけ。自分で付けたほかのタグには触らない。
    途中の階層（``イベント/2026`` など）は残す。写真そのものは消えない。
    ``--year`` で年を絞ったときは、その年のタグだけを対象にする。
    """
    prefix = _managed_prefix(cfg.tag_format)
    if not prefix:
        log.warning("タグのテンプレートに固定の先頭部分（例 'イベント/'）がないため、--prune はしない")
        return
    depth = cfg.tag_format.count("/")
    for value, tag in sorted(by_value.items()):
        if not value.startswith(prefix) or value.count("/") != depth or value in wanted:
            continue
        if cfg.years and not any(f"/{y}/" in f"/{value}/" for y in cfg.years):
            continue
        log.info("%s古いタグを削除: %s", "[dry-run] " if cfg.dry_run else "", value)
        if not cfg.dry_run:
            client.delete_tag(tag["id"])
            stats.tags_deleted += 1


def apply_albums(client: ImmichClient, cfg: Config, events: dict[Event, list[str]], stats: Stats) -> None:
    """イベントごとのアルバムを作り、写真を足す。アルバムから写真を外すことはしない。

    同じ名前のアルバムが自分のアカウントにあれば、それに足す（手で作ったアルバムでも同じ）。

    Args:
        client: Immich のクライアント。
        cfg: 設定。
        events: 今回の対象のイベントと写真 ID。
        stats: 件数を足していく先。
    """
    by_name = {nfc(a["albumName"]): a for a in client.albums()}
    for ev, ids in sorted(events.items(), key=lambda kv: (kv[0].year, kv[0].mmdd, kv[0].name)):
        name = nfc(ev.format(cfg.album_format))
        album = by_name.get(name)
        if cfg.dry_run:
            log.info("[dry-run] アルバム %s%s に %d 枚", name, "" if album else "（新規）", len(ids))
            continue
        if album is None:
            first, rest = ids[:CHUNK], ids[CHUNK:]
            album = client.create_album(name, first)
            by_name[name] = album
            stats.albums_created += 1
            stats.album_added += len(first)
            log.info("アルバムを作成: %s", name)
            ids = rest
        for part in _chunks(ids):
            _count(client.add_album_assets(album["id"], part), stats, "album_added", "already_in_album")


@contextlib.contextmanager
def locked(path: str) -> Iterator[None]:
    """鍵のファイルで、ほかの実行が終わるまで待ってから中に入る。

    全体の実行（timer）と見張りモードが同時にアルバムを作ると、同じ名前のアルバムが
    2 つできることがあるため。``path`` が空なら何もしない。
    """
    if not path:
        yield
        return
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def run(cfg: Config, client: ImmichClient | None = None, paths: Iterable[str] | None = None) -> Stats:
    """1 回分の処理をする。

    Args:
        cfg: 設定。
        client: テスト用に差し替えるクライアント。省略時は ``cfg`` から作る。
        paths: 調べるフォルダ（コンテナの中のパス）。省略時はすべてのフォルダ（全体の実行）。

    Returns:
        件数。
    """
    client = client or ImmichClient(cfg.url, cfg.api_key)
    stats = Stats()
    events = collect_events(client, cfg, stats, paths)
    stats.events = len(events)
    stats.assets = sum(len(v) for v in events.values())
    log.info("イベント %d 件、写真 %d 枚（規則に合わないフォルダ %d 件）", stats.events, stats.assets, stats.skipped_folders)
    if cfg.mode in ("tag", "both") and events:
        apply_tags(client, cfg, events, stats)
    if cfg.mode in ("album", "both") and events:
        apply_albums(client, cfg, events, stats)
    log.info(
        "完了: タグ追加 %d（付いていた %d）、アルバム追加 %d（入っていた %d、新規アルバム %d）、タグ削除 %d、エラー %d",
        stats.tagged, stats.already_tagged, stats.album_added, stats.already_in_album,
        stats.albums_created, stats.tags_deleted, stats.errors,
    )
    return stats


Snapshot = dict[str, int]
"""フォルダの相対パス（``""`` は NAS の写真のフォルダそのもの）と更新時刻（ナノ秒）の対応。"""


def snapshot_dirs(top: str) -> Snapshot:
    """NAS の写真のフォルダの下にあるすべてのフォルダの更新時刻を集める。

    フォルダに写真を足したり消したりすると、そのフォルダの更新時刻が変わる。ファイルを
    1 枚ずつ見ないので、写真が何万枚あっても、見るのはフォルダの数（数百）だけで済む。
    隠しフォルダ（``.webaxs`` など）は見ない。

    Args:
        top: NAS の写真のフォルダ（例 ``/mnt/nas/photos``）。

    Returns:
        フォルダの相対パスと更新時刻の対応。

    Raises:
        OSError: ``top`` が読めないとき（NAS がマウントされていないなど）。
    """
    snap: Snapshot = {"": os.stat(top).st_mtime_ns}
    stack = [""]
    while stack:
        rel = stack.pop()
        try:
            with os.scandir(os.path.join(top, rel) if rel else top) as it:
                for e in it:
                    if e.name.startswith(".") or not e.is_dir(follow_symlinks=False):
                        continue
                    child = f"{rel}/{e.name}" if rel else e.name
                    snap[child] = e.stat(follow_symlinks=False).st_mtime_ns
                    stack.append(child)
        except FileNotFoundError:
            continue  # 見ている間に消えたフォルダ
    return snap


def changed_dirs(before: Snapshot, after: Snapshot) -> set[str]:
    """更新時刻が変わった・増えたフォルダ（相対パス）。消えたフォルダは含めない。"""
    return {k for k, v in after.items() if before.get(k) != v}


def find_library_id(client: ImmichClient, root: str) -> str:
    """``root`` を取り込んでいる外部ライブラリの ID を探す。

    Raises:
        ImmichError: 見つからないとき、2 つ以上あるとき。
    """
    root = root.rstrip("/")
    hits = [lib["id"] for lib in client.libraries()
            if any(p.rstrip("/") == root for p in lib.get("importPaths", []))]
    if len(hits) != 1:
        raise ImmichError(f"フォルダ {root} を取り込んでいる外部ライブラリが {len(hits)} 件（LIBRARY_ID で指定する）")
    return hits[0]


def wait_for_scan(client: ImmichClient, timeout: float, sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.monotonic) -> bool:
    """スキャンを頼んだあと、ライブラリのジョブがなくなるまで待つ。

    頼んですぐはジョブがまだ見えないことがあるので、少なくとも数秒は待つ。

    Returns:
        時間内に終わったら ``True``。
    """
    start = clock()
    sleep(3)
    while clock() - start < timeout:
        if not client.library_queue_busy():
            return True
        sleep(3)
    return False


class Watcher:
    """見張りモード。NAS のフォルダの更新時刻を見て、変わったフォルダだけを処理する。

    1. ``interval`` 秒ごとにフォルダの更新時刻を集める
    2. 変わったフォルダを覚えておき、コピーが終わって更新時刻が止まるまで（1 回分変わらないまで）待つ
    3. Immich に外部ライブラリのスキャンを頼み、終わるまで待つ
    4. 変わったフォルダの写真だけを、アルバム（とタグ）に入れる

    Args:
        cfg: 設定。
        client: Immich のクライアント。
        snapshot: 更新時刻を集める関数（テストで差し替える）。
        sleep: 待つ関数（テストで差し替える）。
    """

    def __init__(self, cfg: Config, client: ImmichClient,
                 snapshot: Callable[[str], Snapshot] = snapshot_dirs,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.cfg = cfg
        self.client = client
        self.snapshot = snapshot
        self.sleep = sleep
        self.last: Snapshot | None = None
        self.pending: set[str] = set()
        self.dirty = False  # 前回の見張りで変化があり、止まるのを待っている
        self.library_id = cfg.library_id

    def to_container(self, rel: str) -> str:
        """NAS の相対パスを、Immich のコンテナの中のパスにする。"""
        root = self.cfg.root.rstrip("/")
        return f"{root}/{rel}" if rel else root

    def tick(self) -> Stats | None:
        """1 回分の見張り。処理したときは件数を返す。"""
        try:
            snap = self.snapshot(self.cfg.nas_dir)
        except OSError as e:
            log.warning("NAS のフォルダを読めない（マウントを確認）: %s", e)
            return None
        if self.last is None:
            self.last = snap
            log.info("見張りを開始: フォルダ %d 件、%d 秒ごと", len(snap), self.cfg.watch_interval)
            return None
        changed = changed_dirs(self.last, snap)
        removed = set(self.last) - set(snap)
        self.last = snap
        if changed or removed:
            self.pending |= changed
            self.pending -= removed
            log.info("変化を検出: %d フォルダ（止まるまで待つ）", len(changed) + len(removed))
            self.dirty = True
            return None
        if not self.dirty:
            return None
        return self.process()

    def process(self) -> Stats:
        """スキャンを頼み、変わったフォルダを処理する。"""
        targets = sorted(self.pending)
        self.pending = set()
        self.dirty = False
        if not self.library_id:
            self.library_id = find_library_id(self.client, self.cfg.root)
        if self.cfg.dry_run:
            log.info("[dry-run] スキャンを頼むはずだった（ライブラリ %s）", self.library_id)
        else:
            log.info("スキャンを依頼: ライブラリ %s", self.library_id)
            self.client.scan_library(self.library_id)
            if not wait_for_scan(self.client, self.cfg.scan_timeout, self.sleep):
                log.warning("スキャンが %d 秒で終わらなかった。今ある分だけ処理し、残りは次の全体の実行で入る",
                            self.cfg.scan_timeout)
        paths = [self.to_container(rel) for rel in targets]
        with locked(self.cfg.lock_file):
            return run(self.cfg, self.client, paths)

    def loop(self) -> None:
        """止められるまで見張り続ける。Immich のエラーはログに出して続ける。"""
        while True:
            try:
                self.tick()
            except ImmichError as e:
                log.error("%s", e)
            self.sleep(self.cfg.watch_interval)


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def parse_args(argv: list[str] | None = None, env: dict[str, str] | None = None) -> Config:
    """コマンドラインと環境変数から設定を作る。引数が環境変数より優先される。

    Raises:
        SystemExit: URL や API キーがないとき、設定が正しくないとき。
    """
    env = dict(os.environ if env is None else env)
    p = argparse.ArgumentParser(description="イベントフォルダを、年付きのフォルダ名の Immich のアルバムにする")
    p.add_argument("--mode", choices=["album", "tag", "both"], default=env.get("MODE", "album"))
    p.add_argument("--dry-run", action="store_true", default=_bool(env.get("DRY_RUN")),
                   help="書き込まずに、することだけをログに出す")
    p.add_argument("--prune", action="store_true", default=_bool(env.get("PRUNE")),
                   help="イベントフォルダがなくなったタグを消す（MODE=tag / both のとき）")
    p.add_argument("--year", action="append", default=None, help="対象の年（複数指定可）")
    p.add_argument("--watch", action="store_true",
                   help="見張りモード。NAS の変化を見つけたらスキャンを頼み、変わったフォルダだけを処理する")
    p.add_argument("--verbose", "-v", action="store_true")
    a = p.parse_args(argv)

    url = env.get("IMMICH_URL", "http://localhost:2283")
    key = env.get("IMMICH_API_KEY", "")
    if not key:
        p.error("IMMICH_API_KEY がない（/etc/immich-event-tagger/tagger.env を確認）")
    years = set(a.year or [y for y in env.get("YEARS", "").split(",") if y.strip()])
    cfg = Config(
        url=url,
        api_key=key,
        root=env.get("PHOTOS_ROOT", DEFAULT_PHOTOS_ROOT),
        mode=a.mode,
        tag_format=env.get("TAG_FORMAT", DEFAULT_TAG_FORMAT),
        album_format=env.get("ALBUM_FORMAT", DEFAULT_ALBUM_FORMAT),
        exclude=env.get("EXCLUDE", ""),
        years={y.strip() for y in years},
        prune=a.prune,
        dry_run=a.dry_run,
        nas_dir=env.get("NAS_PHOTOS_DIR", DEFAULT_NAS_PHOTOS_DIR),
        library_id=env.get("LIBRARY_ID", ""),
        lock_file=env.get("LOCK_FILE", DEFAULT_LOCK_FILE),
    )
    try:
        cfg.watch_interval = float(env.get("WATCH_INTERVAL", "60"))
        cfg.scan_timeout = float(env.get("SCAN_TIMEOUT", "900"))
    except ValueError as e:
        p.error(f"WATCH_INTERVAL / SCAN_TIMEOUT が数字ではない: {e}")
    if a.watch and cfg.prune:
        p.error("--prune は見張りモードでは使えない（全体の実行で使う）")
    cfg.watch = a.watch
    try:
        Event("2000", "0101", "x").format(cfg.tag_format)
        Event("2000", "0101", "x").format(cfg.album_format)
        re.compile(cfg.exclude)
    except (KeyError, IndexError, ValueError, re.error) as e:
        p.error(f"TAG_FORMAT / ALBUM_FORMAT / EXCLUDE が正しくない: {e}")
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return cfg


def main(argv: list[str] | None = None) -> int:
    """コマンドとして実行したときの入口。

    Returns:
        終了コード。0 は成功、1 は一部の写真で失敗、2 は API に接続できないなど。
    """
    cfg = parse_args(argv)
    if cfg.watch:
        Watcher(cfg, ImmichClient(cfg.url, cfg.api_key)).loop()
        return 0
    try:
        with locked(cfg.lock_file):
            stats = run(cfg)
    except ImmichError as e:
        log.error("%s", e)
        return 2
    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(main())
