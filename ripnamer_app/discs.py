"""Disc names and show matching for the headless commands (no Tk, no I/O of its own).

parse_disc_name: "Show - Season 2 - Disc 1" -> {"show": "Show", "season": 2, "disc": 1}
"""

import re

_SEP = r"[\s\-:,]"
_DISC = re.compile(
    rf"^(?P<show>.*?)(?:^|{_SEP}+)(?:season|series|s){_SEP}*(?P<season>\d+)"
    rf"{_SEP}*(?:disc|disk|d){_SEP}*(?P<disc>\d+){_SEP}*$", re.I)


def parse_disc_name(name: str):
    """{show, season, disc} from a disc label like "<show> - Season 2 - Disc 1", "<SHOW> SEASON 1 DISC 1",
    "<show> S1 D2", "<SHOW>_S01_DISC_3" or "<show> Series 1 Disc 2" (case-insensitive, "_" as a space,
    "-", ":" or "," between parts). Season and disc must both be there and 1-99, else None.
    show is the text before the season part, trimmed of separators (may be "")."""
    text = (name or "").replace("_", " ").strip()
    m = _DISC.match(text)
    if not m:
        return None
    season, disc = int(m.group("season")), int(m.group("disc"))
    if not (1 <= season <= 99 and 1 <= disc <= 99):
        return None
    show = re.sub(r"\s+", " ", m.group("show").strip(" \t-:,"))
    return {"show": show, "season": season, "disc": disc}
