"""Disc names and show matching for the headless commands (no Tk, no I/O of its own).

parse_disc_name: "Show - Season 2 - Disc 1" -> {"show": "Show", "season": 2, "disc": 1}
match_show:      a show name -> the one TMDb show it can only be, or a refusal naming the candidates
"""

import re

from .planner import show_label

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


STUDIO_PREFIXES = ("marvel studios", "marvels", "disney", "dc")


def normalise(name: str) -> str:
    """Compare form of a show name: case-folded, apostrophes and punctuation dropped, "&" as "and",
    a leading "the" dropped. "The Spectacular Spider-Man" -> "spectacular spiderman"."""
    s = (name or "").casefold().replace("&", " and ")
    s = re.sub(r"[^\w\s]|_", "", s)
    s = " ".join(s.split())
    return s[4:] if s.startswith("the ") else s


def _strip_studio(norm: str) -> str:
    changed = True
    while changed:
        changed = False
        for p in STUDIO_PREFIXES:
            if norm.startswith(p + " "):
                norm, changed = normalise(norm[len(p) + 1:]), True
    return norm


def _pick(tmdb, results, query_norm, season):
    """The one result whose name is query_norm, or None. Several with that name: the newest one,
    but only when it is the only one of them with that season number."""
    same = [r for r in results if normalise(r["name"]) == query_norm]
    if len(same) == 1:
        return same[0], ""
    if len(same) < 2 or season is None:
        return None, ""
    years = sorted((r["year"] for r in same), reverse=True)
    if not years[0] or years[0] == years[1]:
        return None, ""
    newest = next(r for r in same if r["year"] == years[0])
    have = [r for r in same if season in tmdb.show_details(r["id"])]
    if have == [newest]:
        return newest, f", the only one with season {season}"
    return None, ""


def match_show(tmdb, show: str, season=None):
    """(show {id, name, year} | None, reason). Accepted only if exactly one TMDb result's normalised name
    equals the normalised query (ties: see _pick); retried once without a studio prefix ("Marvel Studios'
    Loki" -> "Loki"); otherwise refused, naming the candidates. TMDbError propagates (never a guess)."""
    query = (show or "").strip()
    q = normalise(query)
    if not q:
        return None, "No show name to look up."
    seen = {}
    tries = [(query, q)]
    bare = _strip_studio(q)
    if bare and bare != q:
        tries.append((bare, bare))
    for i, (text, norm) in enumerate(tries):
        results = tmdb.search_tv(text)
        for r in results:
            seen.setdefault(r["id"], r)
        hit, why = _pick(tmdb, results, norm, season)
        if hit:
            out = {"id": hit["id"], "name": hit["name"], "year": hit["year"]}
            how = " (studio prefix removed)" if i else ""
            return out, f'Matched "{query}" to {show_label(out)}{how}{why}.'
    if not seen:
        return None, f'No show on TMDb matches "{query}".'
    names = [show_label(r) for r in list(seen.values())[:6]]
    return None, "Not sure which show: " + ", ".join(names) + "."
