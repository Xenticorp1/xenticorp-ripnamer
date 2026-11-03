"""Headless commands: disc names, show matching and the plan / apply CLI (no GUI, no network).

    python -m unittest discover -s tests -v
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ripnamer_app import cli, discs, media, mover, planner, tmdb  # noqa: E402
from test_core import (METAL_FILES, METAL_SHOW, WHO, FakeResp, http_error, make_mkv,  # noqa: E402
                       metal_episodes)

REPO = Path(__file__).resolve().parents[1]


def _r(id_, name, date):
    return {"id": id_, "name": name, "first_air_date": date, "overview": ""}


# Fake TMDb, answered by URL path; /search/tv by the (case-folded) query. Made-up ids.
FAKE = {
    "/search/tv": {
        "spectacular spider-man": [_r(101, "The Spectacular Spider-Man", "2008-03-08"),
                                   _r(102, "Spider-Man", "1994-11-19"), _r(103, "Spider-Man", "2017-08-19")],
        "spider-man": [_r(102, "Spider-Man", "1994-11-19"), _r(103, "Spider-Man", "2017-08-19"),
                       _r(104, "Spider-Man", "1981-09-12")],
        "doctor who": [_r(201, "Doctor Who", "1963-11-23"), _r(202, "Doctor Who", "2005-03-26")],
        "marvel studios loki": [_r(301, "Marvel Studios: Assembled", "2021-03-12")],
        "loki": [_r(302, "Loki", "2021-06-09"), _r(303, "Loki: Behind the Scenes", "2021-07-01")],
        "unknown show": [],
    },
    "/tv/102": {"seasons": [{"season_number": 1, "episode_count": 13}, {"season_number": 2, "episode_count": 13},
                            {"season_number": 3, "episode_count": 13}]},
    "/tv/103": {"seasons": [{"season_number": 1, "episode_count": 26}]},
    "/tv/104": {"seasons": [{"season_number": 1, "episode_count": 13}]},
    "/tv/201": {"seasons": [{"season_number": n, "episode_count": 10} for n in range(1, 27)]},
    "/tv/202": {"seasons": [{"season_number": n, "episode_count": 13} for n in range(1, 14)]},
}


def fake_client(routes=None, calls=None, fail=None):
    """TMDb client answering from routes (default FAKE); fail = exception raised for every request."""
    routes = routes or FAKE

    def opener(req, timeout):
        url = urllib.parse.urlsplit(req.full_url)
        path = url.path.removeprefix("/3")
        if calls is not None:
            calls.append(path)
        if fail is not None:
            raise fail
        data = routes[path]
        if path == "/search/tv":
            q = urllib.parse.parse_qs(url.query)["query"][0].casefold()
            data = {"results": data.get(q, [])}
        return FakeResp(json.dumps(data).encode())
    return tmdb.TMDb("k" * 32, opener=opener, sleep=lambda s: None)


class DiscNameTests(unittest.TestCase):
    def test_reads_disc_names(self):
        for name, want in (
                ("Spectacular Spider-Man - Season 1 - Disc 1", ("Spectacular Spider-Man", 1, 1)),
                ("Spectacular Spider-Man - Season 2 - Disc 2", ("Spectacular Spider-Man", 2, 2)),
                ("MARVEL STUDIOS' LOKI SEASON 1 DISC 1", ("MARVEL STUDIOS' LOKI", 1, 1)),
                ("Show S1 D2", ("Show", 1, 2)),
                ("SHOW_S01_DISC_3", ("SHOW", 1, 3)),
                ("Series 1 Disc 2", ("", 1, 2)),
                ("Some Show: Series 3, Disc 4", ("Some Show", 3, 4)),
                ("show season 12 disk 10", ("show", 12, 10)),
                ("Show S01D02", ("Show", 1, 2))):
            got = discs.parse_disc_name(name)
            self.assertEqual((got["show"], got["season"], got["disc"]), want, name)

    def test_not_a_season_disc(self):
        for name in ("Marvel's The Avengers", "ERNEST_SAVES_CHRISTMAS", "DISC_1", "Season 0 Disc 1", "",
                     None, "Show Season 1", "Show Season 100 Disc 1", "Show Season 1 Disc 0",
                     "Show Season 1 Disc 1 Bonus", "Bosses1 D2", "Season 1Disc"):
            self.assertIsNone(discs.parse_disc_name(name), name)


class MatchShowTests(unittest.TestCase):
    def test_exact_name_after_normalising(self):
        show, why = discs.match_show(fake_client(), "Spectacular Spider-Man")
        self.assertEqual(show, {"id": 101, "name": "The Spectacular Spider-Man", "year": "2008"})
        self.assertIn("The Spectacular Spider-Man (2008)", why)

    def test_normalise(self):
        self.assertEqual(discs.normalise("The Spectacular Spider-Man"), discs.normalise("SPECTACULAR SPIDER-MAN"))
        self.assertEqual(discs.normalise("Marvel’s Agents of S.H.I.E.L.D."), "marvels agents of shield")
        self.assertEqual(discs.normalise("Law & Order"), "law and order")
        self.assertEqual(discs.normalise("  The   Office "), "office")

    def test_studio_prefix_retry(self):
        calls = []
        show, why = discs.match_show(fake_client(calls=calls), "MARVEL STUDIOS' LOKI")
        self.assertEqual(show, {"id": 302, "name": "Loki", "year": "2021"})
        self.assertIn("studio prefix removed", why)
        self.assertEqual(calls.count("/search/tv"), 2)  # one retry, no more

    def test_ambiguous_is_refused_with_candidates(self):
        show, why = discs.match_show(fake_client(), "Spider-Man")
        self.assertIsNone(show)
        self.assertEqual(why, "Not sure which show: Spider-Man (1994), Spider-Man (2017), Spider-Man (1981).")
        # a season only the 1994 show has doesn't help: the newest one must be the only one with it
        self.assertIsNone(discs.match_show(fake_client(), "Spider-Man", season=3)[0])

    def test_tie_broken_by_newest_only_when_it_alone_has_the_season(self):
        self.assertIsNone(discs.match_show(fake_client(), "Doctor Who", season=2)[0])  # both have a season 2
        self.assertIsNone(discs.match_show(fake_client(), "Doctor Who")[0])            # no season: refuse
        self.assertIsNone(discs.match_show(fake_client(), "Doctor Who", season=14)[0])  # older only
        routes = dict(FAKE, **{"/tv/201": {"seasons": [{"season_number": 1, "episode_count": 10}]}})
        show, why = discs.match_show(fake_client(routes), "Doctor Who", season=2)
        self.assertEqual(show["id"], 202)
        self.assertIn("only one with season 2", why)

    def test_unknown_and_empty(self):
        self.assertEqual(discs.match_show(fake_client(), "Unknown Show"),
                         (None, 'No show on TMDb matches "Unknown Show".'))
        self.assertIsNone(discs.match_show(fake_client(), "")[0])

    def test_prefix_retry_still_refuses_names_from_both_searches(self):
        routes = dict(FAKE, **{"/search/tv": dict(FAKE["/search/tv"], loki=[
            _r(302, "Loki", "2021-06-09"), _r(305, "Loki", "2016-01-01")])})
        show, why = discs.match_show(fake_client(routes), "Marvel Studios Loki")
        self.assertIsNone(show)
        self.assertEqual(why, "Not sure which show: Marvel Studios: Assembled (2021), Loki (2021), Loki (2016).")

    def test_tmdb_error_is_raised_not_guessed(self):
        with self.assertRaises(tmdb.TMDbError):
            discs.match_show(fake_client(fail=http_error(401)), "Loki")


# ----------------------------------------------------------------------------- CLI

def _season(n, eps):
    return {"episodes": [{"episode_number": e, "name": f"Episode {e}", "runtime": rt, "air_date": None}
                         for e, rt in eps]}


# Metalocalypse as TMDb would serve metal_episodes(): S1 E1-12 (E5, E8 without runtime), S2 E1-3, 15 min
METAL_TMDB = {
    "/tv/1960": {"name": "Metalocalypse", "first_air_date": "2006-08-06",
                 "seasons": [{"season_number": 1, "episode_count": 12}, {"season_number": 2, "episode_count": 3}]},
    "/tv/1960/season/1": _season(1, [(e, None if e in (5, 8) else 15) for e in range(1, 13)]),
    "/tv/1960/season/2": _season(2, [(e, 15) for e in range(1, 4)]),
}
WHO_TMDB = dict(WHO, **{
    "/tv/57243": dict(WHO["/tv/57243"], name="Doctor Who", first_air_date="2005-03-26"),
    "/search/tv": {"doctor who": [_r(57243, "Doctor Who", "2005-03-26"), _r(9, "Doctor Who Confidential", "2005")]},
})
WHO_LIB = "Doctor Who (2005) [tmdbid-57243]"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.rips = self.dir / "rips"
        self.lib = self.dir / "lib"
        self.rips.mkdir()
        self.lib.mkdir()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def cli(self, *argv, routes=WHO_TMDB, key="k" * 32, fail=None):
        """(exit code, parsed JSON) of one cli.run, with a fake TMDb and the key in the environment."""
        out, env = io.StringIO(), {k: v for k, v in os.environ.items() if k != cli.KEY_ENV}
        if key:
            env[cli.KEY_ENV] = key
        with mock.patch.dict(os.environ, env, clear=True):
            code = cli.run([str(a) for a in argv], lambda k: fake_client(routes, fail=fail), out)
        text = out.getvalue()
        self.assertEqual(text.count("\n"), 1)  # exactly one JSON object
        return code, json.loads(text)

    def rip(self, *durs):
        for i, d in enumerate(durs):
            make_mkv(self.rips / f"title_t{i:02}.mkv", d)

    def who_plan(self, *durs, **kw):
        self.rip(*durs)
        return self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, "--start-episode", 12, **kw)

    # ---- plan

    def test_metalocalypse_same_as_planner(self):
        for name, d in METAL_FILES:
            make_mkv(self.rips / name, d)
        code, out = self.cli("plan", self.rips, "--show-id", 1960, "--season", 1, routes=METAL_TMDB)
        want = planner.plan(media.scan_folder(self.rips), metal_episodes(), METAL_SHOW, 1, 5, {},
                            ep_length=None, tolerance=0.25, max_minutes=0, leave_named=True)
        by_num = {e["number"]: e for e in metal_episodes()}
        self.assertEqual([r["file"] for r in out["rows"]], [r["path"].name for r in want])
        for got, w in zip(out["rows"], want):
            ep = by_num[w["number"]] if w["dest"] else None
            self.assertEqual((got["include"], got["status"], got["season"], got["episode"]),
                             (w["include"], w["status"], ep and ep["season"], ep and ep["episode"]), got["file"])
        self.assertEqual(out["show"], {"id": 1960, "name": "Metalocalypse", "year": "2006"})
        self.assertEqual(out["last"], {"season": 1, "episode": 9})
        # off-length extras and already-named files need a person: not clean
        self.assertEqual((code, out["clean"]), (3, False))
        self.assertIn("METALOCALYPSE_t03.mkv: skip: 5:34 vs ~11:34 episode", out["reasons"])
        self.assertIn("s1 e1.mkv: skip: already named S01E01", out["reasons"])
        self.assertNotIn("METALOCALYPSE_t06.mkv", " ".join(out["reasons"]))  # short extra: fine

    def test_who_disc_across_seasons_is_clean(self):
        code, out = self.who_plan(2700, 2700, 2700, 2700, 100)
        self.assertEqual((code, out["ok"], out["clean"], out["reasons"]), (0, True, True, []))
        self.assertEqual(out["v"], 1)
        self.assertEqual(out["show"], {"id": 57243, "name": "Doctor Who", "year": "2005"})
        self.assertEqual((out["season"], out["start"], out["last"]), (1, 12, {"season": 2, "episode": 2}))
        self.assertEqual([r["dest"] for r in out["rows"]], [
            f"{WHO_LIB}/Season 01/Doctor Who (2005) - S01E12 - Bad Wolf.mkv",
            f"{WHO_LIB}/Season 01/Doctor Who (2005) - S01E13 - The Parting of the Ways.mkv",
            f"{WHO_LIB}/Season 02/Doctor Who (2005) - S02E01 - New Earth.mkv",
            f"{WHO_LIB}/Season 02/Doctor Who (2005) - S02E02 - Tooth and Claw.mkv", None])
        first, extra = out["rows"][0], out["rows"][4]
        self.assertEqual({k: first[k] for k in ("file", "seconds", "include", "status", "season", "episode", "title")},
                         {"file": "title_t00.mkv", "seconds": 2700, "include": True, "status": "OK",
                          "season": 1, "episode": 12, "title": "Bad Wolf"})
        self.assertEqual(first["size"], (self.rips / "title_t00.mkv").stat().st_size)
        self.assertEqual((extra["include"], extra["status"], extra["season"]), (False, "skip: extra (short)", None))
        self.assertEqual(list(self.lib.iterdir()), [])  # plan touches nothing
        self.assertEqual(len(list(self.rips.iterdir())), 5)

    def test_who_special_on_disc_is_not_clean_with_specials_off(self):
        code, out = self.who_plan(2700, 2700, 3600, 2700, 2700)
        self.assertEqual((code, out["ok"], out["clean"]), (3, True, False))
        self.assertEqual(out["reasons"], ["title_t02.mkv: skip: 60:00 vs ~45:00 episode"])
        # with --specials it is in the timeline, and the disc is clean again
        code, out = self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, "--start-episode", 12,
                             "--specials")
        self.assertEqual((code, out["clean"]), (0, True))
        self.assertEqual(out["rows"][2]["dest"], f"{WHO_LIB}/Season 00/Doctor Who (2005) - S00E02 - The Christmas Invasion.mkv")

    def test_more_files_than_episodes_and_unreadable_are_not_clean(self):
        code, out = self.who_plan(2700, 2700, 2700, 2700, 2700)
        self.assertEqual(code, 3)
        self.assertEqual(out["reasons"], ["title_t04.mkv: no episode #5 here"])
        (self.rips / "title_t05.mkv").write_bytes(b"not a video" * 100)
        with mock.patch.object(media.shutil, "which", return_value=None):
            code, out = self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, "--start-episode", 12)
        self.assertIn("title_t05.mkv: skip: unreadable", out["reasons"])

    def test_empty_folder_is_not_clean(self):
        code, out = self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, "--start-episode", 12)
        self.assertEqual((code, out["clean"], out["rows"], out["last"]), (3, False, [], None))

    def test_disc_name_finds_the_show(self):
        self.rip(2700, 2700)
        code, out = self.cli("plan", self.rips, "--disc-name", "DOCTOR_WHO_S1_D4", "--start-episode", 12)
        self.assertEqual((code, out["show"]["id"], out["season"]), (0, 57243, 1))
        code, out = self.cli("plan", self.rips, "--disc-name", "Doctor Who Confidential? Season 1 Disc 1",
                             routes=dict(WHO_TMDB, **{"/search/tv": {}}))
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertIn("No show on TMDb", out["error"])

    def test_start_not_in_timeline_is_an_error(self):
        code, out = self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, "--start-episode", 3)
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertIn("S01E03 isn't in the TMDb timeline", out["error"])

    def test_no_key_and_tmdb_errors_never_guess(self):
        self.rip(2700)
        code, out = self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, key=None)
        self.assertEqual((code, out), (1, {"v": 1, "ok": False,
                                           "error": "No TMDb key: pass --key-file PATH or set RIPNAMER_TMDB_KEY."}))
        code, out = self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, fail=http_error(401))
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertIn("401", out["error"])
        code, out = self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, fail=http_error(503))
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertNotIn("rows", out)

    def test_key_file(self):
        self.rip(2700)
        seen = []
        keyfile = self.dir / "key.txt"
        keyfile.write_text("fake-key-from-file\n")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {cli.KEY_ENV: "fake-env-key"}):
            cli.run(["plan", str(self.rips), "--show-id", "57243", "--season", "1", "--start-episode", "12",
                     "--key-file", str(keyfile)], lambda k: seen.append(k) or fake_client(WHO_TMDB), out)
        self.assertEqual(seen, ["fake-key-from-file"])
        code, res = self.cli("plan", self.rips, "--show-id", 57243, "--season", 1, "--key-file", self.dir / "nope")
        self.assertEqual((code, res["ok"]), (1, False))

    def test_bad_arguments_exit_2(self):
        for argv in ([], ["plan", self.rips], ["plan", self.rips, "--show-id", 1],
                     ["plan", self.rips, "--show-id", 1, "--disc-name", "X S1 D1"],
                     ["plan", self.rips, "--disc-name", "ERNEST_SAVES_CHRISTMAS"],
                     ["plan", self.rips, "--disc-name", "Season 1 Disc 1"],
                     ["plan", self.dir / "nope", "--show-id", 1, "--season", 1],
                     ["plan", self.rips, "--show-id", "x", "--season", 1],
                     ["plan", self.rips, "--show-id", 1, "--season", 1, "--start-episode", 0],
                     ["apply", self.rips], ["apply", self.rips, "--plan", "p.json", "--dest", self.dir / "nope"],
                     ["frobnicate"]):
            code, out = self.cli(*argv)
            self.assertEqual((code, out["ok"]), (2, False), argv)

    # ---- apply

    def write_plan(self, plan):
        p = self.dir / "plan.json"
        p.write_text(json.dumps(plan))
        return p

    def apply(self, plan):
        return self.cli("apply", self.rips, "--plan", self.write_plan(plan), "--dest", self.lib)

    def test_apply_moves_into_the_library_and_can_be_undone(self):
        _, plan = self.who_plan(2700, 2700, 2700, 2700, 100)
        code, out = self.apply(plan)
        self.assertEqual((code, out["ok"], out["moved"], out["errors"]), (0, True, 4, []))
        log = Path(out["log"])
        self.assertEqual(log.parent, self.rips)
        for r in plan["rows"][:4]:
            self.assertTrue((self.lib / r["dest"]).is_file())
            self.assertFalse((self.rips / r["file"]).exists())
        self.assertTrue((self.rips / "title_t04.mkv").exists())  # the extra stays
        self.assertEqual(json.loads(log.read_text())["moves"][0],
                         [str(self.rips / "title_t00.mkv"), str(self.lib / plan["rows"][0]["dest"])])
        restored, errors, _ = mover.undo(log)
        self.assertEqual((restored, errors), (4, []))
        self.assertEqual(len(list(self.rips.glob("title_t*.mkv"))), 5)

    def test_apply_refuses_unclean_plan(self):
        _, plan = self.who_plan(2700, 2700, 3600, 2700, 2700)
        code, out = self.apply(plan)
        self.assertEqual((code, out["ok"], out["moved"], out["log"]), (1, False, 0, None))
        self.assertIn("not clean", out["error"])
        plan["clean"], plan["reasons"] = True, []  # hand-edited to "clean": the rows still say no
        code, out = self.apply(plan)
        self.assertEqual(code, 1)
        self.assertIn("title_t02.mkv: skipped but not as an extra (skip: 60:00 vs ~45:00 episode)", out["errors"])
        self.assertEqual(list(self.lib.iterdir()), [])

    def test_apply_refuses_changed_or_missing_files(self):
        _, plan = self.who_plan(2700, 2700, 2700, 2700)
        with open(self.rips / "title_t01.mkv", "ab") as f:
            f.write(b"more")
        (self.rips / "title_t03.mkv").unlink()
        code, out = self.apply(plan)
        self.assertEqual((code, out["moved"]), (1, 0))
        self.assertTrue(any(e.startswith("title_t01.mkv: changed since the plan") for e in out["errors"]))
        self.assertIn("title_t03.mkv: missing", out["errors"])
        self.assertTrue((self.rips / "title_t00.mkv").exists())  # all or nothing: nothing moved
        self.assertEqual(list(self.lib.iterdir()), [])

    def test_apply_refuses_existing_target(self):
        _, plan = self.who_plan(2700, 2700, 2700, 2700)
        target = self.lib / plan["rows"][2]["dest"]
        target.parent.mkdir(parents=True)
        target.write_bytes(b"already here")
        code, out = self.apply(plan)
        self.assertEqual((code, out["moved"]), (1, 0))
        self.assertTrue(any("already exists" in e for e in out["errors"]))
        self.assertEqual(target.read_bytes(), b"already here")
        self.assertTrue((self.rips / "title_t00.mkv").exists())

    def test_apply_refuses_dest_outside_the_library(self):
        _, plan = self.who_plan(2700, 2700, 2700, 2700)
        good = plan["rows"][0]["dest"]
        name = good.rsplit("/", 1)[1]
        for bad in ("../escape/Season 01/" + name, str(self.dir / "abs" / "Season 01" / name),
                    "/abs/Season 01/" + name, WHO_LIB + "/Season 01/../../" + name,
                    WHO_LIB + "/Season 01/bad\x07name.mkv", WHO_LIB + "/Season 01/a\nb.mkv",
                    "C:/x/Season 01/" + name, "..\\x\\Season 01\\" + name, WHO_LIB + "/" + name,
                    WHO_LIB + "/Season 01/sub/" + name, "", None):
            p = json.loads(json.dumps(plan))
            p["rows"][0]["dest"] = bad
            code, out = self.apply(p)
            self.assertEqual((code, out["moved"]), (1, 0), bad)
        # a show folder that is a link to somewhere else also leaves the library
        outside = self.dir / "outside"
        outside.mkdir()
        try:
            (self.lib / WHO_LIB).symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        code, out = self.apply(plan)
        self.assertEqual((code, out["moved"]), (1, 0))
        self.assertTrue(any("leaves the library" in e for e in out["errors"]))
        self.assertEqual(list(outside.iterdir()), [])

    def test_apply_refuses_bad_plan_files(self):
        self.rip(2700)
        for plan in ({"v": 2, "ok": True, "clean": True, "rows": []}, [], {"v": 1, "ok": True, "clean": True, "rows": []},
                     {"v": 1, "ok": True, "clean": True, "rows": [
                         {"file": "../title_t00.mkv", "size": 1, "include": True, "status": "OK", "dest": "a"}]}):
            code, out = self.apply(plan)
            self.assertEqual((code, out["ok"], out["moved"]), (1, False, 0), plan)
        p = self.dir / "garbage.json"
        p.write_text("{not json")
        code, out = self.cli("apply", self.rips, "--plan", p, "--dest", self.lib)
        self.assertEqual((code, out["ok"]), (1, False))

    def test_runs_as_a_module_without_tkinter(self):
        notk = self.dir / "notk"
        notk.mkdir()
        (notk / "sitecustomize.py").write_text("import sys\nsys.modules['tkinter'] = None\n")
        env = {k: v for k, v in os.environ.items() if k != cli.KEY_ENV}
        env["PYTHONPATH"] = os.pathsep.join([str(notk), str(REPO)])
        r = subprocess.run([sys.executable, "-c", "import tkinter"], env=env, capture_output=True, cwd=REPO)
        self.assertNotEqual(r.returncode, 0)  # the block works
        r = subprocess.run([sys.executable, "-m", "ripnamer_app.cli", "plan", str(self.rips), "--show-id", "1",
                            "--season", "1"], env=env, capture_output=True, text=True, cwd=REPO, timeout=60)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(json.loads(r.stdout)["error"], "No TMDb key: pass --key-file PATH or set RIPNAMER_TMDB_KEY.")
        r = subprocess.run([sys.executable, "-c", "import sys, ripnamer_app.cli; print('tkinter' in sys.modules)"],
                           env=dict(env, PYTHONPATH=str(REPO)), capture_output=True, text=True, cwd=REPO, timeout=60)
        self.assertEqual(r.stdout.strip(), "False", r.stderr)


if __name__ == "__main__":
    unittest.main()
