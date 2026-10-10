"""Turns scanned files + TMDb episodes into a rename plan. Pure logic, no I/O besides exists() checks."""

import re
from pathlib import Path

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe(name: str) -> str:
    """Strip characters Windows won't allow in file names."""
    name = _BAD.sub("", name).strip().rstrip(".")
    return re.sub(r"\s+", " ", name) or "_"


def show_label(show: dict) -> str:
    return f"{show['name']} ({show['year']})" if show.get("year") else show["name"]


def row_kind(row: dict) -> str:
    """'skip' | 'bad' | 'warn' | 'ok' - drives colours and counts."""
    s = row["status"]
    if not row["include"]:
        return "skip"
    if s.startswith(("CONFLICT", "no ")):
        return "bad"
    return "warn" if s.startswith("CHECK") else "ok"


def is_ready(row: dict) -> bool:
    """Will be renamed/moved: OK or CHECK, has a target, and the target isn't already its name."""
    return (row_kind(row) in ("ok", "warn") and row["dest"] is not None
            and Path(row["dest"]) != Path(row["path"]))


def mmss(sec) -> str:
    """694 -> '11:34'"""
    m, s = divmod(int(round(sec)), 60)
    return f"{m}:{s:02}"


def parse_length(text: str):
    """'11:34' or '11' / '11.5' (minutes) -> seconds; '' -> None (Auto). ValueError if unreadable."""
    text = text.strip()
    if not text:
        return None
    if ":" in text:
        m, _, s = text.partition(":")
        sec = int(m or 0) * 60 + int(s)
        if not 0 <= int(s) < 60:
            raise ValueError(text)
    else:
        sec = round(float(text) * 60)
    if sec <= 0:
        raise ValueError(text)
    return sec


# "S01E02", "s1 e2", "S01.E02", "s1e2" and "1x02" - not "title_t01" or "1920x1080"
_NAMED = (re.compile(r"(?<![a-z0-9])s(\d{1,2})[ ._-]*e(\d{1,3})(?!\d)", re.I),
          re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?![\dp])", re.I))


def parse_named(name: str):
    """(season, episode) if a file name already says which episode it is, else None."""
    stem = Path(name).stem
    for rx in _NAMED:
        m = rx.search(stem)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return (xs[n // 2] + xs[(n - 1) // 2]) / 2


def auto_length(files, min_minutes):
    """Median length of the files at or above the Settings minimum: the "Auto" episode length."""
    durs = [f["duration"] for f in files if f["duration"] and f["duration"] >= min_minutes * 60]
    return _median(durs) if durs else None


def calibration(pairs):
    """Factor between real file lengths and TMDb runtimes on this disc (e.g. 694 s files for
    '15 min' episodes -> 0.77), from (seconds, tmdb_minutes) pairs. Needs >= 3 pairs that agree
    within 10% of the median and make up at least half of them; otherwise 1.0 (trust TMDb)."""
    ratios = [d / (rt * 60) for d, rt in pairs if d and rt]
    if len(ratios) < 3:
        return 1.0
    med = _median(ratios)
    agree = [r for r in ratios if abs(r / med - 1) <= 0.10]
    return _median(agree) if len(agree) >= 3 and len(agree) * 2 >= len(ratios) else 1.0


def plan(files, episodes, show, start_ep, min_minutes, overrides, library_root=None, anchors=None,
         ep_length=None, tolerance=0.25, max_minutes=0, leave_named=True, strict=False):
    """
    files:       [{"path": Path, "duration": sec}]
    episodes:    [{"number", "title", "runtime", "season", "episode"}]
                 'number' = position counted from start_ep; season/episode = what goes in the name.
                 Entries with pick_only=True are used only for anchored files, never by counting.
    show:        {"id", "name", "year"}
    overrides:   {str(path): True/False} manual include/skip
    anchors:     {str(path): number} "Set episode…": that file gets episode #number and the
                 files after it keep counting from there
    ep_length:   seconds a real episode on this disc lasts; None = Auto (median file length)
    tolerance:   files further than this fraction from ep_length are skipped as extras; also the
                 runtime CHECK threshold (at least 1 minute)
    max_minutes: files longer than this are skipped; 0 = off (then ~1.8x ep_length = play-all)
    leave_named: files already named SxxEyy / 1x02 are skipped (True) or pinned to that episode
                 and only tidied to the standard name (False). Either way counting skips their episodes.
    strict:      no automatic skipping: every file in order gets the next episode
    Matching is by order + anchors only; lengths decide auto-skips and CHECKs, never which episode.
    Returns rows: {path, duration, include, dest, status, number, anchored, named}
    """
    anchors = anchors or {}
    floor = min_minutes * 60
    length = ep_length or auto_length(files, min_minutes)
    ep_by_num = {e["number"]: e for e in episodes}
    num_by_code = {(e["season"], e["episode"]): e["number"] for e in episodes}
    label = show_label(show)

    # already-named files: their episodes are taken, so counting jumps over them
    named = {}
    for f in files:
        key = str(f["path"])
        code = parse_named(f["path"].name)
        if code and key not in anchors and overrides.get(key) is not False:
            named[key] = (code, num_by_code.get(code))
    claimed = {n for _, n in named.values() if n is not None}

    # A file off the disc's usual length is still an episode if it fits the TMDb runtime of the
    # episode it would get (a 60-min special among 45-min episodes, a double-length finale).
    # TMDb minutes are scaled to this disc: usual length / typical TMDb runtime of these episodes.
    window = [ep_by_num[n].get("runtime") for n in range(start_ep, start_ep + len(files) + len(claimed))
              if n in ep_by_num]
    window = [rt for rt in window if rt]
    scale = length / (_median(window) * 60) if length and window else None

    def fits_next(d, number):
        while number in claimed:
            number += 1
        rt = (ep_by_num.get(number) or {}).get("runtime")
        if not (scale and rt and d):
            return False
        want = rt * 60 * scale
        return abs(d - want) <= max(60, want * tolerance)

    # pass 1: decide include/skip and which episode each file gets
    picks, next_ep = [], start_ep
    for f in files:
        p, d, key = f["path"], f["duration"], str(f["path"])
        row = {"path": p, "duration": d, "include": True, "dest": None, "status": "",
               "number": None, "anchored": False, "named": False}
        picks.append(row)
        if overrides.get(key) is False:
            row.update(include=False, status="skip: manual")
            continue
        if key in anchors:
            row.update(number=anchors[key], anchored=True)
            next_ep = anchors[key] + 1
            continue
        if key in named:
            (season, epn), num = named[key]
            code = f"S{season:02}E{epn:02}"
            if num is None and overrides.get(key) is not True:  # included by hand: counts like any file
                row.update(include=False, status=f"skip: named {code} (not in this list)")
                continue
            if num is not None and leave_named and overrides.get(key) is not True:
                row.update(include=False, status=f"skip: already named {code}")
                continue
            if num is not None:  # pinned: keeps its episode, at most tidied to the standard name
                row.update(number=num, named=True)
                continue
        reason = None
        if not strict and overrides.get(key) is not True:
            if d is None:
                reason = "skip: unreadable"
            elif d < floor:
                reason = "skip: extra (short)"
            elif max_minutes and d > max_minutes * 60:
                reason = "skip: over max length"
            elif length and not max_minutes and d > length * 1.8 and not fits_next(d, next_ep):
                reason = "skip: play-all?"
            elif length and abs(d - length) > length * tolerance and not fits_next(d, next_ep):
                reason = f"skip: {mmss(d)} vs ~{mmss(length)} episode"
        if reason:
            row.update(include=False, status=reason)
            continue
        while next_ep in claimed:
            next_ep += 1
        row["number"], next_ep = next_ep, next_ep + 1

    # pass 2: names, runtime checks, conflicts
    def ep_for(row):
        ep = ep_by_num.get(row["number"])
        return None if ep is None or (ep.get("pick_only") and not row["anchored"]) else ep
    factor = 1.0 if ep_length else calibration(
        [(r["duration"], ep_for(r).get("runtime")) for r in picks if r["number"] is not None and ep_for(r)])
    used = set()
    for row in picks:
        if row["number"] is None:
            continue
        p, d, ep = row["path"], row["duration"], ep_for(row)
        if ep is None:
            row["status"] = f"no episode #{row['number']} here"
            continue
        season, epn = ep["season"], ep["episode"]
        fname = safe(f"{label} - S{season:02}E{epn:02} - {ep['title']}") + p.suffix.lower()
        if library_root:
            dest = Path(library_root) / safe(f"{label} [tmdbid-{show['id']}]") / f"Season {season:02}" / fname
        else:
            dest = p.with_name(fname)

        expected = ep_length or (ep["runtime"] * 60 * factor if ep.get("runtime") else None)
        if row["anchored"]:
            status = "OK (set)"
        elif row["named"]:
            status = "OK (already named)"
        elif expected is None:
            status = "OK (no TMDb runtime)"
        else:
            status = "OK"
        if expected and d and abs(d - expected) > max(60, expected * tolerance):
            status = f"CHECK: expected ~{mmss(expected)}"
        if dest.exists() and dest.resolve() != p.resolve():
            status = "CONFLICT: exists"
        if str(dest).lower() in used:
            status = "CONFLICT: duplicate"
        used.add(str(dest).lower())
        row.update(dest=dest, status=status)
    return picks
