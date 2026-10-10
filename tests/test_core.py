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
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import make_version_info  # noqa: E402
from ripnamer_app import VERSION, media, mover, planner, tmdb  # noqa: E402

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
        f = self.files(4380, 1452, 1448, 190, 1460, 1455)
        episodes = eps(10, ["A", "B", "C", "D"])
        episodes[2]["runtime"] = 40  # TMDb says C is long; the file isn't -> CHECK, not a skip
        rows = planner.plan(f, episodes, SHOW, 10, 10, {})
        self.assertEqual([r["status"] for r in rows],
                         ["skip: play-all?", "OK", "OK", "skip: extra (short)", "CHECK: expected ~40:20", "OK"])
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

    def test_anchor_continues_counting_from_set_episode(self):
        f = self.files(1452, 1448, 1460, 1450, 1455)
        rows = planner.plan(f, eps(1, list("ABCDEFGHIJ")), SHOW, 1, 10, {},
                            anchors={str(f[2]["path"]): 7})
        self.assertEqual([r["number"] for r in rows], [1, 2, 7, 8, 9])
        self.assertEqual([r["status"] for r in rows], ["OK", "OK", "OK (set)", "OK", "OK"])
        self.assertTrue(rows[2]["anchored"] and not rows[3]["anchored"])
        self.assertIn("S01E08 - H", rows[3]["dest"].name)

    def test_anchored_row_still_gets_runtime_check(self):
        f = self.files(1452, 600 * 6)
        rows = planner.plan(f, eps(1, ["A", "B", "C"]), SHOW, 1, 10, {}, anchors={str(f[1]["path"]): 3})
        self.assertEqual(rows[1]["status"], "CHECK: expected ~24:00")

    def test_specials_go_to_season_00(self):
        f = self.files(1452, 3600)
        special = {"number": 2, "title": "The Christmas Invasion", "runtime": 60, "season": 0, "episode": 2}
        rows = planner.plan(f, eps(1, ["A"]) + [special], SHOW, 1, 10, {}, library_root=self.dir / "lib")
        rel = rows[1]["dest"].relative_to(self.dir / "lib")
        self.assertEqual(rel.parts[1], "Season 00")
        self.assertEqual(rel.name, "Cowboy Bebop (1998) - S00E02 - The Christmas Invasion.mkv")

    def test_pick_only_episode_needs_an_anchor(self):
        f = self.files(1452, 1448)
        extra = {"number": 2, "title": "X", "runtime": 24, "season": 0, "episode": 9, "pick_only": True}
        rows = planner.plan(f, eps(1, ["A"]) + [extra], SHOW, 1, 10, {})
        self.assertEqual(rows[1]["status"], "no episode #2 here")
        rows = planner.plan(f, eps(1, ["A"]) + [extra], SHOW, 1, 10, {}, anchors={str(f[1]["path"]): 2})
        self.assertEqual(rows[1]["status"], "OK (set)")

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

class VersionInfoTests(unittest.TestCase):
    def test_exe_details_follow_version(self):
        text = make_version_info.render("3.1.3")
        self.assertIn("filevers=(3, 1, 3, 0), prodvers=(3, 1, 3, 0)", text)
        self.assertIn("StringStruct('FileDescription', 'Xenticorp Ripnamer v3.1.3')", text)
        self.assertIn("StringStruct('ProductVersion', '3.1.3')", text)
        self.assertIn("filevers=(4, 0, 0, 0)", make_version_info.render("4.0"))
        self.assertIn(f"'{VERSION}'", make_version_info.render(VERSION))


class NamingHelperTests(unittest.TestCase):
    def test_parse_named(self):
        P = planner.parse_named
        self.assertEqual(P("s1 e1.mkv"), (1, 1))
        self.assertEqual(P("Metalocalypse (2006) - S01E02 - Dethklok.mkv"), (1, 2))
        self.assertEqual(P("show.S02.E10.mkv"), (2, 10))
        self.assertEqual(P("s2e12.mp4"), (2, 12))
        self.assertEqual(P("Show 1x02.mkv"), (1, 2))
        for name in ("title_t01.mkv", "METALOCALYPSE_t03.mkv", "rip 1920x1080.mkv", "Bosses1e2.mkv",
                     "Show 2x720p.mkv"):
            self.assertIsNone(P(name), name)

    def test_parse_length(self):
        self.assertEqual(planner.parse_length("11:34"), 694)
        self.assertEqual(planner.parse_length(" 11 "), 660)
        self.assertEqual(planner.parse_length("11.5"), 690)
        self.assertIsNone(planner.parse_length(""))
        for bad in ("abc", "1:75", "0", "-3"):
            with self.assertRaises(ValueError, msg=bad):
                planner.parse_length(bad)

    def test_calibration_needs_three_agreeing_pairs(self):
        self.assertAlmostEqual(planner.calibration([(694, 15)] * 3), 694 / 900)
        self.assertEqual(planner.calibration([(694, 15)] * 2), 1.0)
        self.assertEqual(planner.calibration([(694, 15), (900, 15), (1400, 15), (300, 15)]), 1.0)
        self.assertEqual(planner.calibration([(694, 15), (694, None)] * 2), 1.0)  # missing runtimes don't count


# Metalocalypse S1 disc 1 as ripped: seven 11:34 episodes, extras of 5:34, 4:13 and 20:18, and
# three files already named by hand that natural order puts after the "METALOCALYPSE…" ones.
METAL_FILES = [("METALOCALYPSE_t00.mkv", 694), ("METALOCALYPSE_t01.mkv", 694), ("METALOCALYPSE_t02.mkv", 694),
               ("METALOCALYPSE_t03.mkv", 334), ("METALOCALYPSE_t04.mkv", 694), ("METALOCALYPSE_t05.mkv", 694),
               ("METALOCALYPSE_t06.mkv", 253), ("METALOCALYPSE_t07.mkv", 694), ("METALOCALYPSE_t08.mkv", 1218),
               ("METALOCALYPSE_t09.mkv", 694), ("s1 e1.mkv", 694), ("s1 e3.mkv", 694), ("s2 e1.mkv", 694)]
METAL_SHOW = {"id": 1960, "name": "Metalocalypse", "year": "2006"}


def metal_episodes():
    """Continuous timeline: S1 E1-12 then S2 E1-3, TMDb says 15 min, two have no runtime."""
    out = [{"number": n, "title": f"Episode {n}", "runtime": None if n in (5, 8) else 15,
            "season": 1 if n <= 12 else 2, "episode": n if n <= 12 else n - 12} for n in range(1, 16)]
    return out


class EpisodeLengthTests(TmpDir):
    def setUp(self):
        super().setUp()
        self.f = []
        for name, d in METAL_FILES:
            (self.dir / name).write_bytes(b"")
            self.f.append({"path": self.dir / name, "duration": d})

    def plan(self, **kw):
        rows = planner.plan(self.f, metal_episodes(), METAL_SHOW, 1, 5, {}, **kw)
        return {r["path"].name: r for r in rows}

    def test_auto_length_skips_extras_without_false_checks(self):
        self.assertEqual(planner.auto_length(self.f, 5), 694)
        rows = self.plan()
        self.assertEqual(rows["METALOCALYPSE_t03.mkv"]["status"], "skip: 5:34 vs ~11:34 episode")
        self.assertEqual(rows["METALOCALYPSE_t06.mkv"]["status"], "skip: extra (short)")
        self.assertEqual(rows["METALOCALYPSE_t08.mkv"]["status"], "skip: 20:18 vs ~11:34 episode")
        statuses = [r["status"] for r in rows.values()]
        self.assertFalse([s for s in statuses if s.startswith("CHECK")])
        self.assertEqual(statuses.count("OK (no TMDb runtime)"), 2)  # E5 and E8: neutral
        # episodes 1, 3 and 13 belong to the hand-named files, so counting jumps over them
        self.assertEqual([rows[f"METALOCALYPSE_t0{i}.mkv"]["number"] for i in (0, 1, 2, 4, 5, 7, 9)],
                         [2, 4, 5, 6, 7, 8, 9])
        for name, code in (("s1 e1.mkv", "S01E01"), ("s1 e3.mkv", "S01E03"), ("s2 e1.mkv", "S02E01")):
            self.assertEqual(rows[name]["status"], f"skip: already named {code}")  # left alone (default)
            self.assertFalse(rows[name]["include"])

    def test_already_named_pinned_and_tidied_when_not_left_alone(self):
        rows = self.plan(leave_named=False)
        for name, n, code in (("s1 e1.mkv", 1, "S01E01"), ("s1 e3.mkv", 3, "S01E03"), ("s2 e1.mkv", 13, "S02E01")):
            self.assertEqual((rows[name]["number"], rows[name]["status"]), (n, "OK (already named)"))
            self.assertIn(f" - {code} - ", rows[name]["dest"].name)
            self.assertTrue(planner.is_ready(rows[name]))  # loose name -> tidied to the standard one
        self.assertEqual(rows["METALOCALYPSE_t00.mkv"]["number"], 2)

    def test_already_standard_name_is_not_renamed(self):
        std = self.dir / "Metalocalypse (2006) - S01E01 - Episode 1.mkv"
        std.write_bytes(b"")
        rows = planner.plan([{"path": std, "duration": 694}], metal_episodes(), METAL_SHOW, 1, 5, {},
                            leave_named=False)
        self.assertEqual(rows[0]["status"], "OK (already named)")
        self.assertFalse(planner.is_ready(rows[0]))

    def test_named_file_outside_this_list_and_manual_include(self):
        f = [{"path": self.dir / "s3 e9.mkv", "duration": 694}, {"path": self.dir / "s1 e3.mkv", "duration": 694}]
        rows = planner.plan(f, metal_episodes(), METAL_SHOW, 1, 5, {str(f[1]["path"]): True})
        self.assertEqual(rows[0]["status"], "skip: named S03E09 (not in this list)")
        self.assertEqual((rows[1]["number"], rows[1]["status"]), (3, "OK (already named)"))  # included by hand

    def test_max_length(self):
        rows = self.plan(max_minutes=15, tolerance=1.0)
        self.assertEqual(rows["METALOCALYPSE_t08.mkv"]["status"], "skip: over max length")
        rows = self.plan(max_minutes=0, tolerance=1.0)
        self.assertTrue(rows["METALOCALYPSE_t08.mkv"]["include"])  # max rule off (and < 1.8x: no play-all)

    def test_manual_length_overrides_auto(self):
        rows = self.plan(ep_length=planner.parse_length("20:18"))
        self.assertTrue(rows["METALOCALYPSE_t08.mkv"]["include"])
        self.assertEqual(rows["METALOCALYPSE_t08.mkv"]["status"], "OK")
        self.assertEqual(rows["METALOCALYPSE_t00.mkv"]["status"], "skip: 11:34 vs ~20:18 episode")

    def test_manual_length_drives_checks(self):
        rows = self.plan(ep_length=694, tolerance=0.05)
        self.assertFalse([r for r in rows.values() if r["status"].startswith("CHECK")])
        # threshold is max(1 min, tolerance): strict keeps the files so only the CHECK rule applies
        rows = self.plan(ep_length=660, tolerance=0.05, strict=True)  # off by 34 s: under the 1-min floor
        self.assertEqual(rows["METALOCALYPSE_t00.mkv"]["status"], "OK")
        rows = self.plan(ep_length=600, tolerance=0.05, strict=True)  # off by 94 s
        self.assertEqual(rows["METALOCALYPSE_t00.mkv"]["status"], "CHECK: expected ~10:00")
        rows = self.plan(ep_length=600, tolerance=0.20, strict=True)  # 20% of 10:00 = 2 min > 94 s
        self.assertEqual(rows["METALOCALYPSE_t00.mkv"]["status"], "OK")

    def test_strict_order_skips_nothing(self):
        rows = self.plan(strict=True)
        metal = [r for n, r in rows.items() if n.startswith("METALOCALYPSE")]
        self.assertTrue(all(r["include"] for r in metal))
        self.assertEqual([r["number"] for r in metal], [2, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        self.assertEqual(rows["METALOCALYPSE_t03.mkv"]["status"], "CHECK: expected ~11:34")


# Doctor Who (2005): the Christmas special aired between series 1 and 2.
WHO = {
    "/tv/57243": {"seasons": [{"season_number": 0, "episode_count": 2}, {"season_number": 1, "episode_count": 2},
                              {"season_number": 2, "episode_count": 2}, {"season_number": 3, "episode_count": 0}]},
    "/tv/57243/season/1": {"episodes": [
        {"episode_number": 12, "name": "Bad Wolf", "runtime": 45, "air_date": "2005-06-11"},
        {"episode_number": 13, "name": "The Parting of the Ways", "runtime": 45, "air_date": "2005-06-18"}]},
    "/tv/57243/season/0": {"episodes": [
        {"episode_number": 2, "name": "The Christmas Invasion", "runtime": 60, "air_date": "2005-12-25"},
        {"episode_number": 3, "name": "Attack of the Graske", "runtime": 10, "air_date": None}]},
    "/tv/57243/season/2": {"episodes": [
        {"episode_number": 1, "name": "New Earth", "runtime": 45, "air_date": "2006-04-15"},
        {"episode_number": 2, "name": "Tooth and Claw", "runtime": 45, "air_date": "2006-04-22"}]},
}


def who_client(calls=None):
    """TMDb client that answers from WHO by URL path; records each path in calls."""
    def opener(req, timeout):
        path = urllib.parse.urlsplit(req.full_url).path.removeprefix("/3")
        if calls is not None:
            calls.append(path)
        return FakeResp(json.dumps(WHO[path]).encode())
    return tmdb.TMDb("k" * 32, opener=opener, sleep=lambda s: None)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.t = who_client(self.calls)

    @staticmethod
    def codes(episodes):
        return [f"S{e['season']:02}E{e['episode']:02}" for e in episodes]

    def test_show_details_lists_seasons_with_episodes(self):
        self.assertEqual(self.t.show_details(57243), [0, 1, 2])

    def test_special_slots_in_by_air_date(self):
        tl = self.t.timeline(57243)
        self.assertEqual(self.codes(tl), ["S01E12", "S01E13", "S00E02", "S02E01", "S02E02"])
        self.assertEqual([e["number"] for e in tl], [1, 2, 3, 4, 5])
        self.assertEqual(tl[2]["air_date"], "2005-12-25")
        self.assertEqual(tmdb.position(tl, 2, 1), 4)
        self.assertIsNone(tmdb.position(tl, 9, 9))

    def test_specials_off(self):
        self.assertEqual(self.codes(self.t.timeline(57243, include_specials=False)),
                         ["S01E12", "S01E13", "S02E01", "S02E02"])

    def test_seasons_fetched_once_and_cache_untouched(self):
        self.t.timeline(57243)
        self.t.timeline(57243, include_specials=False)
        self.assertEqual(sorted(self.calls), sorted(set(self.calls)))
        self.assertEqual([e["number"] for e in self.t.season(57243, 2)], [1, 2])  # not renumbered

    def test_undated_special_only_in_picker(self):
        tl = self.t.timeline(57243)
        self.assertNotIn("S00E03", self.codes(tl))
        picker = self.t.with_all_specials(57243, tl)
        self.assertEqual(self.codes(picker)[-1], "S00E03")
        self.assertEqual((picker[-1]["number"], picker[-1]["pick_only"]), (6, True))
        # specials off: both specials are still pickable
        off = self.t.with_all_specials(57243, self.t.timeline(57243, include_specials=False))
        self.assertEqual(self.codes(off)[-2:], ["S00E02", "S00E03"])


class ContinuousPlanTests(TmpDir):
    def test_disc_spanning_two_seasons_and_a_special(self):
        c = who_client()
        tl = c.with_all_specials(57243, c.timeline(57243))
        files = []
        for i, d in enumerate((2700, 2700, 3600, 2700, 2700)):
            p = self.dir / f"title_t{i:02}.mkv"
            p.write_bytes(b"")
            files.append({"path": p, "duration": d})
        show = {"id": 57243, "name": "Doctor Who", "year": "2005"}
        rows = planner.plan(files, tl, show, tmdb.position(tl, 1, 12), 10, {}, library_root=self.dir / "lib")
        names = [r["dest"].relative_to(self.dir / "lib" / "Doctor Who (2005) [tmdbid-57243]").as_posix()
                 for r in rows]
        self.assertEqual(names, [
            "Season 01/Doctor Who (2005) - S01E12 - Bad Wolf.mkv",
            "Season 01/Doctor Who (2005) - S01E13 - The Parting of the Ways.mkv",
            "Season 00/Doctor Who (2005) - S00E02 - The Christmas Invasion.mkv",
            "Season 02/Doctor Who (2005) - S02E01 - New Earth.mkv",
            "Season 02/Doctor Who (2005) - S02E02 - Tooth and Claw.mkv"])
        self.assertTrue(all(r["status"] == "OK" for r in rows))

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
