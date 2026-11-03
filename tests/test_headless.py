"""Headless commands: disc names, show matching and the plan / apply CLI (no GUI, no network).

    python -m unittest discover -s tests -v
"""

import json
import sys
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ripnamer_app import discs, tmdb  # noqa: E402
from test_core import FakeResp, http_error  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
