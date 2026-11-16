"""event_tagger のテスト。``python3 -m unittest discover immich/tagger`` で実行する。"""

import json
import os
import tempfile
import threading
import unicodedata
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import event_tagger as et


class FakeImmich:
    """Immich API の代わり。呼ばれた書き込みを記録する。"""

    def __init__(self, folders, tags=None, albums=None):
        self.folders = folders  # {path: [asset_id, ...]}
        self._tags = {t["value"]: t for t in (tags or [])}
        self.tagged = {}  # tag_id -> set(asset_id)
        self._albums = {a["albumName"]: a for a in (albums or [])}
        self.album_assets = {}
        self.deleted = []
        self.writes = 0
        self.scans = []
        self.busy = []  # library_queue_busy が順に返す値
        self.folder_calls = []

    def unique_paths(self):
        return list(self.folders)

    def libraries(self):
        return [{"id": "lib1", "importPaths": [ROOT + "/"]}, {"id": "lib2", "importPaths": ["/other"]}]

    def scan_library(self, library_id):
        self.writes += 1
        self.scans.append(library_id)

    def library_queue_busy(self):
        return self.busy.pop(0) if self.busy else False

    def folder_assets(self, path):
        self.folder_calls.append(path)
        return [{"id": i, "isTrashed": i.endswith("-trash")} for i in self.folders[path]]

    def tags(self):
        return list(self._tags.values())

    def upsert_tags(self, values):
        self.writes += 1
        out = []
        for v in values:
            t = self._tags.setdefault(v, {"id": f"t{len(self._tags)}", "value": v, "name": v.rsplit("/", 1)[-1]})
            out.append(t)
        return out

    def tag_assets(self, tag_id, ids):
        self.writes += 1
        have = self.tagged.setdefault(tag_id, set())
        res = []
        for i in ids:
            res.append({"id": i, "success": i not in have, **({} if i not in have else {"error": "duplicate"})})
            have.add(i)
        return res

    def delete_tag(self, tag_id):
        self.writes += 1
        self.deleted.append(tag_id)

    def albums(self):
        return list(self._albums.values())

    def create_album(self, name, ids):
        self.writes += 1
        a = {"id": f"a{len(self._albums)}", "albumName": name}
        self._albums[name] = a
        self.album_assets[a["id"]] = set(ids)
        return a

    def add_album_assets(self, album_id, ids):
        self.writes += 1
        have = self.album_assets.setdefault(album_id, set())
        res = [{"id": i, "success": i not in have, "error": None if i not in have else "duplicate"} for i in ids]
        have.update(ids)
        return res


ROOT = "/mnt/media/photos"
FOLDERS = {
    f"{ROOT}/2026/1003_運動会": ["a1", "a2", "a3-trash"],
    f"{ROOT}/2026/1003_運動会/RAW": ["a4"],
    f"{ROOT}/2025/1227_日常/": ["b1"],
    f"{ROOT}/2025/misc": ["c1"],
    f"{ROOT}/2025/1301_おかしい": ["c2"],
    f"{ROOT}/2025/.webaxs/thumbnail": ["c3"],
    "/data/upload/xxx": ["d1"],
}


def cfg(**kw):
    return et.Config(url="http://x", api_key="k", root=ROOT, **kw)


class ParseEventTest(unittest.TestCase):
    def test_event(self):
        self.assertEqual(et.parse_event(f"{ROOT}/2026/1003_運動会", ROOT), et.Event("2026", "1003", "運動会"))

    def test_subfolder_belongs_to_event(self):
        self.assertEqual(et.parse_event(f"{ROOT}/2026/1003_運動会/RAW/", ROOT).folder, "1003_運動会")

    def test_name_with_underscore(self):
        self.assertEqual(et.parse_event(f"{ROOT}/2026/0505_こどもの日_公園", ROOT).name, "こどもの日_公園")

    def test_not_event(self):
        for p in [f"{ROOT}/2026", f"{ROOT}/2026/misc", f"{ROOT}/2026/1301_x", f"{ROOT}/26/1003_x",
                  f"{ROOT}/2026/1003_", f"{ROOT}/2026/.webaxs", f"{ROOT}/2026/1003_x/.webaxs", "/other/2026/1003_x"]:
            self.assertIsNone(et.parse_event(p, ROOT), p)

    def test_nfd_is_normalized(self):
        nfd = unicodedata.normalize("NFD", "ぶどう狩り")
        self.assertEqual(et.parse_event(f"{ROOT}/2026/0910_{nfd}", ROOT).name, "ぶどう狩り")

    def test_format(self):
        ev = et.Event("2026", "1003", "運動会")
        self.assertEqual(ev.format(et.DEFAULT_TAG_FORMAT), "イベント/2026/1003_運動会")
        self.assertEqual(ev.format(et.DEFAULT_ALBUM_FORMAT), "261003_運動会")
        self.assertEqual(ev.format("{year}-{mm}-{dd} {name}"), "2026-10-03 運動会")


class RunTest(unittest.TestCase):
    def test_default_mode_is_album(self):
        fake = FakeImmich(FOLDERS)
        s = et.run(cfg(), fake)
        self.assertEqual((s.albums_created, s.tagged), (2, 0))
        self.assertEqual(set(fake._albums), {"261003_運動会", "251227_日常"})
        self.assertEqual(fake.album_assets[fake._albums["261003_運動会"]["id"]], {"a1", "a2", "a4"})

    def test_tags_and_idempotent(self):
        fake = FakeImmich(FOLDERS)
        s = et.run(cfg(mode="tag"), fake)
        self.assertEqual((s.events, s.assets, s.tagged, s.skipped_folders), (2, 4, 4, 3))
        tag = fake._tags["イベント/2026/1003_運動会"]
        self.assertEqual(fake.tagged[tag["id"]], {"a1", "a2", "a4"})
        s2 = et.run(cfg(mode="tag"), fake)
        self.assertEqual((s2.tagged, s2.already_tagged, s2.errors), (0, 4, 0))

    def test_dry_run_writes_nothing(self):
        fake = FakeImmich(FOLDERS)
        et.run(cfg(dry_run=True, mode="both", prune=True), fake)
        self.assertEqual(fake.writes, 0)

    def test_exclude_and_year(self):
        fake = FakeImmich(FOLDERS)
        self.assertEqual(et.run(cfg(exclude="^日常$"), fake).events, 1)
        self.assertEqual(set(fake._albums), {"261003_運動会"})
        self.assertEqual(et.run(cfg(years={"2025"}), FakeImmich(FOLDERS)).events, 1)

    def test_albums(self):
        fake = FakeImmich(FOLDERS, albums=[{"id": "old", "albumName": "251227_日常"}])
        s = et.run(cfg(mode="album"), fake)
        self.assertEqual((s.albums_created, s.album_added), (1, 4))
        self.assertEqual(fake.album_assets["old"], {"b1"})
        s2 = et.run(cfg(mode="album"), fake)
        self.assertEqual((s2.albums_created, s2.album_added, s2.already_in_album), (0, 0, 4))

    def test_same_folder_name_in_two_years(self):
        folders = {f"{ROOT}/2026/1003_運動会": ["n1"], f"{ROOT}/2025/1003_運動会": ["o1"]}
        fake = FakeImmich(folders)
        et.run(cfg(), fake)
        self.assertEqual(fake.album_assets[fake._albums["251003_運動会"]["id"]], {"o1"})
        self.assertEqual(fake.album_assets[fake._albums["261003_運動会"]["id"]], {"n1"})

    def test_prune_only_removed_event_tags(self):
        tags = [
            {"id": "keep-parent", "value": "イベント/2024"},
            {"id": "gone", "value": "イベント/2024/0101_旧名"},
            {"id": "mine", "value": "お気に入り/2024/0101_x"},
        ]
        fake = FakeImmich(FOLDERS, tags=tags)
        et.run(cfg(mode="tag", prune=True), fake)
        self.assertEqual(fake.deleted, ["gone"])

    def test_prune_respects_year(self):
        tags = [{"id": "gone", "value": "イベント/2024/0101_旧名"}]
        fake = FakeImmich(FOLDERS, tags=tags)
        et.run(cfg(mode="tag", prune=True, years={"2026"}), fake)
        self.assertEqual(fake.deleted, [])

    def test_prune_needs_prefix(self):
        fake = FakeImmich(FOLDERS, tags=[{"id": "x", "value": "2024/0101_旧名"}])
        et.run(cfg(mode="tag", prune=True, tag_format="{year}/{folder}"), fake)
        self.assertEqual(fake.deleted, [])


class SnapshotTest(unittest.TestCase):
    def test_snapshot_and_changes(self):
        with tempfile.TemporaryDirectory() as top:
            os.makedirs(f"{top}/2026/1003_運動会/RAW")
            os.makedirs(f"{top}/2026/.webaxs/thumbnail")
            before = et.snapshot_dirs(top)
            self.assertEqual(set(before), {"", "2026", "2026/1003_運動会", "2026/1003_運動会/RAW"})
            st = os.stat(f"{top}/2026/1003_運動会")
            os.utime(f"{top}/2026/1003_運動会", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
            os.makedirs(f"{top}/2026/1103_紅葉")
            after = et.snapshot_dirs(top)
            self.assertEqual(et.changed_dirs(before, after), {"2026", "2026/1003_運動会", "2026/1103_紅葉"})

    def test_missing_top(self):
        with self.assertRaises(OSError):
            et.snapshot_dirs("/nonexistent/photos")


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.snaps = []
        self.fake = FakeImmich({
            f"{ROOT}/2026/1003_運動会": ["a1", "a2"],
            f"{ROOT}/2026/1103_紅葉": ["k1"],
            f"{ROOT}/2025/1227_日常": ["b1"],
        })
        self.w = et.Watcher(cfg(lock_file=""), self.fake, snapshot=lambda top: self.snaps.pop(0),
                            sleep=lambda s: None)

    def test_only_changed_folders_after_settle(self):
        base = {"": 1, "2026": 1, "2026/1003_運動会": 1, "2025": 1, "2025/1227_日常": 1}
        new = dict(base, **{"2026": 2, "2026/1103_紅葉": 2})
        self.snaps = [base, base, new, new]
        self.assertIsNone(self.w.tick())  # 最初は覚えるだけ
        self.assertIsNone(self.w.tick())  # 変化なし
        self.assertIsNone(self.w.tick())  # 変化を検出、止まるのを待つ
        self.assertEqual(self.fake.scans, [])
        stats = self.w.tick()  # 止まったので処理
        self.assertEqual(self.fake.scans, ["lib1"])
        self.assertEqual(self.fake.folder_calls, [f"{ROOT}/2026/1103_紅葉"])  # 年フォルダは写真を取りに行かない
        self.assertEqual((stats.events, stats.album_added), (1, 1))
        self.assertEqual(set(self.fake._albums), {"261103_紅葉"})

    def test_waits_while_copy_continues(self):
        a = {"": 1, "2026/1103_紅葉": 1}
        b = {"": 1, "2026/1103_紅葉": 2}
        c = {"": 1, "2026/1103_紅葉": 3}
        self.snaps = [a, b, c, c]
        self.w.tick(); self.w.tick(); self.w.tick()
        self.assertEqual(self.fake.scans, [])
        self.w.tick()
        self.assertEqual(self.fake.scans, ["lib1"])

    def test_nas_unmounted_is_skipped(self):
        def boom(top):
            raise OSError("not mounted")
        w = et.Watcher(cfg(lock_file=""), self.fake, snapshot=boom, sleep=lambda s: None)
        self.assertIsNone(w.tick())
        self.assertIsNone(w.last)

    def test_dry_run_does_not_scan(self):
        a = {"": 1}
        b = {"": 1, "2026/1103_紅葉": 1}
        w = et.Watcher(cfg(lock_file="", dry_run=True), self.fake, snapshot=lambda t: self.snaps.pop(0),
                       sleep=lambda s: None)
        self.snaps = [a, b, b]
        w.tick(); w.tick(); w.tick()
        self.assertEqual(self.fake.writes, 0)

    def test_find_library_id(self):
        self.assertEqual(et.find_library_id(self.fake, ROOT), "lib1")
        with self.assertRaises(et.ImmichError):
            et.find_library_id(self.fake, "/nowhere")

    def test_wait_for_scan(self):
        self.fake.busy = [True, True, False]
        self.assertTrue(et.wait_for_scan(self.fake, 100, sleep=lambda s: None))
        t = iter(range(0, 1000, 50))
        self.fake.busy = [True] * 100
        self.assertFalse(et.wait_for_scan(self.fake, 100, sleep=lambda s: None, clock=lambda: next(t)))

    def test_lock(self):
        with tempfile.TemporaryDirectory() as d:
            with et.locked(f"{d}/x.lock"):
                self.assertTrue(os.path.exists(f"{d}/x.lock"))


class ArgsTest(unittest.TestCase):
    def test_env_and_args(self):
        c = et.parse_args(["--mode", "both", "--year", "2026"], {"IMMICH_API_KEY": "k", "DRY_RUN": "1"})
        self.assertEqual((c.mode, c.years, c.dry_run, c.url), ("both", {"2026"}, True, "http://localhost:2283"))

    def test_watch_args(self):
        c = et.parse_args(["--watch"], {"IMMICH_API_KEY": "k", "WATCH_INTERVAL": "30"})
        self.assertEqual((c.watch, c.watch_interval, c.nas_dir), (True, 30.0, "/mnt/nas/photos"))
        with self.assertRaises(SystemExit):
            et.parse_args(["--watch", "--prune"], {"IMMICH_API_KEY": "k"})

    def test_missing_key(self):
        with self.assertRaises(SystemExit):
            et.parse_args([], {})

    def test_bad_format(self):
        with self.assertRaises(SystemExit):
            et.parse_args([], {"IMMICH_API_KEY": "k", "TAG_FORMAT": "{event}"})


class ClientTest(unittest.TestCase):
    def test_base_url(self):
        self.assertEqual(et.ImmichClient("http://pi:2283/", "k").base, "http://pi:2283/api")
        self.assertEqual(et.ImmichClient("http://pi:2283/api", "k").base, "http://pi:2283/api")

    def test_request_over_http(self):
        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):
                seen["key"] = self.headers["x-api-key"]
                seen["path"] = self.path
                seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                out = json.dumps([{"id": "a1", "success": True}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

            def do_GET(self):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"message":"Invalid API key"}')

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = et.ImmichClient(f"http://127.0.0.1:{srv.server_port}", "secret")
            self.assertEqual(c.tag_assets("t1", ["a1"]), [{"id": "a1", "success": True}])
            self.assertEqual(seen, {"key": "secret", "path": "/api/tags/t1/assets", "body": {"ids": ["a1"]}})
            with self.assertRaisesRegex(et.ImmichError, "HTTP 401"):
                c.tags()
            with self.assertRaisesRegex(et.ImmichError, "HTTP 401"):
                c.library_queue_busy()
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
