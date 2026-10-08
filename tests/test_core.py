"""Core tests (no GUI, no network). Run from the RipNamer folder:

    python -m unittest discover -s tests -v
"""

import errno
import io
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ripnamer_app import media, mover, planner, tmdb  # noqa: E402

# ----------------------------------------------------------------------------- synthetic files


def _vsize(n):  # 1-byte EBML size (n < 127) or 8-byte
    return bytes([0x80 | n]) if n < 127 else b"\x01" + n.to_bytes(7, "big")


def make_mkv(path, seconds):
    info = (b"\x2A\xD7\xB1" + _vsize(3) + (1_000_000).to_bytes(3, "big")
            + b"\x44\x89" + _vsize(8) + struct.pack(">d", seconds * 1000))
    data = (b"\x1A\x45\xDF\xA3" + _vsize(0)
            + b"\x18\x53\x80\x67" + b"\x01\xff\xff\xff\xff\xff\xff\xff"
            + b"\x15\x49\xA9\x66" + _vsize(len(info)) + info
            + b"\x1F\x43\xB6\x75" + _vsize(4) + b"\0" * 4)
    Path(path).write_bytes(data + b"\0" * 2048)


def _atom(kind, body):
    return struct.pack(">I4s", 8 + len(body), kind) + body


def make_mp4(path, seconds, moov_last=False, v1=False, pad=4096):
    scale = 1000
    if v1:
        mvhd = b"\x01\0\0\0" + b"\0" * 16 + struct.pack(">IQ", scale, int(seconds * scale)) + b"\0" * 80
    else:
        mvhd = b"\0\0\0\0" + b"\0" * 8 + struct.pack(">II", scale, int(seconds * scale)) + b"\0" * 80
    moov = _atom(b"moov", _atom(b"mvhd", mvhd))
    ftyp, mdat = _atom(b"ftyp", b"isom\0\0\x02\0"), _atom(b"mdat", b"\0" * pad)
    Path(path).write_bytes(ftyp + (mdat + moov if moov_last else moov + mdat))


class TmpDir(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

# ----------------------------------------------------------------------------- media


class MediaTests(TmpDir):
    def test_mkv_duration(self):
        make_mkv(self.dir / "a.mkv", 1452)
        self.assertAlmostEqual(media.duration(self.dir / "a.mkv"), 1452, places=3)

    def test_mp4_faststart_end_and_v1(self):
        make_mp4(self.dir / "a.mp4", 1448)
        make_mp4(self.dir / "b.mp4", 1500, moov_last=True)
        make_mp4(self.dir / "c.m4v", 60, v1=True)
        self.assertAlmostEqual(media.duration(self.dir / "a.mp4"), 1448)
        self.assertAlmostEqual(media.duration(self.dir / "b.mp4"), 1500)
        self.assertAlmostEqual(media.duration(self.dir / "c.m4v"), 60)

    def test_garbage_is_none(self):
        (self.dir / "x.mkv").write_bytes(b"not a video" * 50)
        with mock.patch.object(media.shutil, "which", return_value=None):
            self.assertIsNone(media.duration(self.dir / "x.mkv"))

    def test_scan_filters_and_natural_sort(self):
        for n in ("title_t10.mkv", "title_t2.mp4", "title_t1.mkv", "notes.txt"):
            (self.dir / n).write_bytes(b"")
        self.assertEqual([p.name for p in media.list_videos(self.dir)],
                         ["title_t1.mkv", "title_t2.mp4", "title_t10.mkv"])

    def test_formatting(self):
        self.assertEqual(media.fmt_dur(4380), "1:13:00")
        self.assertEqual(media.fmt_dur(190), "3:10")
        self.assertEqual(media.fmt_bytes(1536 * 1024 ** 2), "1.5 GB")

# ----------------------------------------------------------------------------- planner

SHOW = {"id": 30991, "name": "Cowboy Bebop", "year": "1998"}


def eps(start, titles, runtime=24, season=1):
    return [{"number": start + i, "title": t, "runtime": runtime, "season": season, "episode": start + i}
            for i, t in enumerate(titles)]


class PlannerTests(TmpDir):
    def files(self, *durs):
        out = []
        for i, d in enumerate(durs):
            p = self.dir / f"title_t{i:02}.mkv"
            p.write_bytes(b"")
            out.append({"path": p, "duration": d})
        return out

    def test_skips_extras_and_play_all_and_flags_runtime(self):
        f = self.files(4380, 1452, 1448, 190, 1100, 1460)
        rows = planner.plan(f, eps(10, ["A", "B", "C", "D"]), SHOW, 10, 10, {})
        self.assertEqual([r["status"] for r in rows],
                         ["skip: play-all?", "OK", "OK", "skip: extra (short)", "CHECK: expected ~24m", "OK"])
        self.assertEqual(rows[1]["dest"].name, "Cowboy Bebop (1998) - S01E10 - A.mkv")
        self.assertEqual(rows[5]["dest"].name, "Cowboy Bebop (1998) - S01E13 - D.mkv")

    def test_overrides_renumber(self):
        f = self.files(1452, 1448, 1460)
        rows = planner.plan(f, eps(1, ["A", "B", "C"]), SHOW, 1, 10, {str(f[0]["path"]): False})
        self.assertEqual(rows[0]["status"], "skip: manual")
        self.assertIn("S01E01 - A", rows[1]["dest"].name)

    def test_more_files_than_episodes(self):
        rows = planner.plan(self.files(1452, 1448), eps(1, ["A"]), SHOW, 1, 10, {})
        self.assertEqual(planner.row_kind(rows[1]), "bad")

    def test_library_layout_and_safe_names(self):
        f = self.files(1452)
        rows = planner.plan(f, eps(1, ['Who: "Me"?']), SHOW, 1, 10, {}, library_root=self.dir / "lib")
        rel = rows[0]["dest"].relative_to(self.dir / "lib")
        self.assertEqual(rel.parts[:2], ("Cowboy Bebop (1998) [tmdbid-30991]", "Season 01"))
        self.assertEqual(rel.name, "Cowboy Bebop (1998) - S01E01 - Who Me.mkv")

    def test_conflict_when_target_exists(self):
        f = self.files(1452)
        (self.dir / "Cowboy Bebop (1998) - S01E01 - A.mkv").write_bytes(b"")
        rows = planner.plan(f, eps(1, ["A"]), SHOW, 1, 10, {})
        self.assertEqual(rows[0]["status"], "CONFLICT: exists")
        self.assertFalse(planner.is_ready(rows[0]))

    def test_scheme_numbering(self):
        self.assertEqual(tmdb.scheme_numbers(["Volume 1", "Volume 2", "Specials", "Pilot arc"]), [1, 2, 0, 3])
        sub = {"number": 3, "episodes": [{"pos": 1, "title": "X", "runtime": 24, "orig_season": 2,
                                          "orig_episode": 7}]}
        self.assertEqual(tmdb.scheme_episodes(sub, "standard")[0]["season"], 2)
        self.assertEqual((tmdb.scheme_episodes(sub, "scheme")[0]["season"],
                          tmdb.scheme_episodes(sub, "scheme")[0]["episode"]), (3, 1))

# ----------------------------------------------------------------------------- TMDb client


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, headers=None):
    return urllib.error.HTTPError("u", code, "x", headers or {}, None)


class TMDbTests(unittest.TestCase):
    def client(self, outcomes):
        """outcomes: list of exceptions or dicts, consumed per request."""
        self.sleeps, it = [], iter(outcomes)

        def opener(req, timeout):
            o = next(it)
            if isinstance(o, BaseException):
                raise o
            return FakeResp(json.dumps(o).encode())
        return tmdb.TMDb("k" * 32, opener=opener, sleep=self.sleeps.append)

    def test_retries_server_errors_then_succeeds(self):
        c = self.client([http_error(502), http_error(503), {"results": []}])
        self.assertEqual(c.search_tv("x"), [])
        self.assertEqual(self.sleeps, [1, 2])

    def test_rate_limit_honours_retry_after(self):
        c = self.client([http_error(429, {"Retry-After": "3"}), {"results": []}])
        c.search_tv("x")
        self.assertEqual(self.sleeps, [3])

    def test_bad_key_fails_fast(self):
        c = self.client([http_error(401)])
        with self.assertRaisesRegex(tmdb.TMDbError, "API key"):
            c.search_tv("x")
        self.assertEqual(self.sleeps, [])

    def test_offline_message_after_all_attempts(self):
        err = urllib.error.URLError(socket.gaierror(-3, "no dns"))
        c = self.client([err] * 4)
        with self.assertRaisesRegex(tmdb.TMDbError, "internet connection. Tried 4 times"):
            c.search_tv("x")
        self.assertEqual(self.sleeps, [1, 2, 4])

    def test_timeout_is_retried(self):
        c = self.client([socket.timeout(), {"results": [{"id": 1, "name": "N", "first_air_date": "1986-09-13"}]}])
        self.assertEqual(c.search_tv("x")[0]["year"], "1986")

    def test_episode_group_parsing(self):
        c = self.client([{"groups": [
            {"name": "Volume 2", "order": 1, "episodes": [
                {"order": 1, "season_number": 1, "episode_number": 6, "name": "B"},
                {"order": 0, "season_number": 1, "episode_number": 5, "name": "A"}]},
            {"name": "Volume 1", "order": 0, "episodes": []}]}])
        subs = c.episode_group("g")
        self.assertEqual([s["name"] for s in subs], ["Volume 1", "Volume 2"])
        self.assertEqual([e["title"] for e in subs[1]["episodes"]], ["A", "B"])
        self.assertEqual(subs[1]["number"], 2)

# ----------------------------------------------------------------------------- mover


class MoverTests(TmpDir):
    def setUp(self):
        super().setUp()
        self.src_dir = self.dir / "rips"
        self.src_dir.mkdir()
        self.lib = self.dir / "lib"

    def row(self, name, size, dest_name):
        p = self.src_dir / name
        p.write_bytes(os.urandom(size))
        return {"path": p, "duration": 1440, "include": True, "status": "OK",
                "dest": self.lib / "Show" / "Season 01" / dest_name}

    def cross_device(self):
        """Pretend every rename crosses drives, like rips on D: and library on a NAS."""
        real = os.rename

        def fake(a, b):
            raise OSError(errno.EXDEV, "cross-device link")
        return mock.patch.object(mover.os, "rename", side_effect=fake), real

    def test_same_drive_rename_and_undo(self):
        rows = [self.row("t00.mkv", 1000, "E01.mkv"), self.row("t01.mkv", 2000, "E02.mkv")]
        prog = mover.Progress()
        n, log, errors, cancelled = mover.execute(rows, self.src_dir, prog)
        self.assertEqual((n, errors, cancelled), (2, [], False))
        self.assertEqual(prog.snapshot()["bytes_done"], 3000)
        self.assertTrue((self.lib / "Show/Season 01/E02.mkv").exists())
        restored, errors, cancelled = mover.undo(log)
        self.assertEqual((restored, errors), (2, []))
        self.assertTrue((self.src_dir / "t00.mkv").exists())
        self.assertFalse(self.lib.joinpath("Show").exists())  # empty dirs tidied
        self.assertTrue(log.with_suffix(".undone.json").exists())

    def test_cross_drive_copy_with_progress(self):
        data_row = self.row("t00.mkv", 5 * 1024 * 1024, "E01.mkv")
        original = data_row["path"].read_bytes()
        patch, _ = self.cross_device()
        with patch, mock.patch.object(mover, "CHUNK", 1024 * 1024):
            prog = mover.Progress()
            n, log, errors, _ = mover.execute([data_row], self.src_dir, prog)
        self.assertEqual((n, errors), (1, []))
        self.assertFalse(data_row["path"].exists())
        self.assertEqual(data_row["dest"].read_bytes(), original)
        self.assertEqual(prog.snapshot()["bytes_done"], len(original))
        self.assertEqual(list(data_row["dest"].parent.glob("*" + mover.PART_SUFFIX)), [])

    def test_cancel_mid_copy_leaves_original_and_no_partial(self):
        r1, r2 = self.row("t00.mkv", 4 * 1024 * 1024, "E01.mkv"), self.row("t01.mkv", 1024, "E02.mkv")
        cancel = threading.Event()
        prog = mover.Progress()
        real_advance = prog.advance

        def advance(n):  # cancel after the first 1 MB block
            real_advance(n)
            cancel.set()
        prog.advance = advance
        patch, _ = self.cross_device()
        with patch, mock.patch.object(mover, "CHUNK", 1024 * 1024):
            n, log, errors, cancelled = mover.execute([r1, r2], self.src_dir, prog, cancel)
        self.assertEqual((n, cancelled, log), (0, True, None))
        self.assertTrue(r1["path"].exists() and r2["path"].exists())
        self.assertFalse(r1["dest"].exists())
        self.assertEqual(list(self.lib.rglob("*" + mover.PART_SUFFIX)), [])

    def test_not_enough_space(self):
        r = self.row("t00.mkv", 1024, "E01.mkv")
        patch, _ = self.cross_device()
        usage = shutil._ntuple_diskusage(10, 10, 0) if hasattr(shutil, "_ntuple_diskusage") else \
            mock.Mock(free=0)
        with patch, mock.patch.object(mover.shutil, "disk_usage", return_value=usage):
            n, log, errors, _ = mover.execute([r], self.src_dir)
        self.assertEqual(n, 0)
        self.assertIn("not enough space", errors[0])
        self.assertTrue(r["path"].exists())

    def test_log_written_incrementally_and_partial_undo_resumable(self):
        rows = [self.row(f"t0{i}.mkv", 100, f"E0{i}.mkv") for i in range(3)]
        n, log, errors, _ = mover.execute(rows, self.src_dir)
        self.assertEqual(len(json.loads(log.read_text())["moves"]), 3)
        # block one restore: something else now uses the original name
        (self.src_dir / "t01.mkv").write_bytes(b"squatter")
        restored, errors, _ = mover.undo(log)
        self.assertEqual(restored, 2)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(json.loads(log.read_text())["moves"]), 1)  # only the failed one remains
        (self.src_dir / "t01.mkv").unlink()
        restored, errors, _ = mover.undo(log)
        self.assertEqual((restored, errors), (1, []))

    def test_copy_that_cannot_delete_source_is_undoable(self):
        r = self.row("t00.mkv", 2048, "E01.mkv")
        patch, _ = self.cross_device()
        with patch, mock.patch.object(mover.os, "remove", side_effect=PermissionError("locked")):
            n, log, errors, _ = mover.execute([r], self.src_dir)
        self.assertEqual(n, 1)
        self.assertIn("couldn't be deleted", errors[0])
        restored, errors, _ = mover.undo(log)
        self.assertEqual((restored, errors), (1, []))
        self.assertTrue(r["path"].exists())
        self.assertFalse(r["dest"].exists())


if __name__ == "__main__":
    unittest.main()
