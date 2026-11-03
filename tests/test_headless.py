"""Headless commands: disc names, show matching and the plan / apply CLI (no GUI, no network).

    python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ripnamer_app import discs  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
