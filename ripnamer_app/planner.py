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
    return row_kind(row) in ("ok", "warn") and row["dest"] is not None


def plan(files, episodes, show, start_ep, min_minutes, overrides, library_root=None, anchors=None):
    """
    files:      [{"path": Path, "duration": sec}]
    episodes:   [{"number", "title", "runtime", "season", "episode"}]
                'number' = position counted from start_ep; season/episode = what goes in the name.
                Entries with pick_only=True are used only for anchored files, never by counting.
    show:       {"id", "name", "year"}
    overrides:  {str(path): True/False} manual include/skip
    anchors:    {str(path): number} "Set episode…": that file gets episode #number and the
                files after it keep counting from there
    Returns rows: {path, duration, include, dest, status, number, anchored}
    """
    anchors = anchors or {}
    durs = sorted(f["duration"] for f in files if f["duration"] and f["duration"] >= min_minutes * 60)
    median = durs[len(durs) // 2] if durs else None
    ep_by_num = {e["number"]: e for e in episodes}
    label = show_label(show)
    rows, used, next_ep = [], set(), start_ep

    for f in files:
        p, d = f["path"], f["duration"]
        auto, reason = True, ""
        if d is None:
            auto, reason = False, "skip: unreadable"
        elif d < min_minutes * 60:
            auto, reason = False, "skip: extra (short)"
        elif median and len(durs) >= 3 and d > median * 1.8:
            auto, reason = False, "skip: play-all?"
        include = overrides.get(str(p), auto)
        if not include:
            rows.append({"path": p, "duration": d, "include": False, "dest": None,
                         "status": "skip: manual" if str(p) in overrides else reason,
                         "number": None, "anchored": False})
            continue

        anchored = str(p) in anchors
        epnum = anchors[str(p)] if anchored else next_ep
        next_ep = epnum + 1
        ep = ep_by_num.get(epnum)
        if ep is None or (ep.get("pick_only") and not anchored):
            rows.append({"path": p, "duration": d, "include": True, "dest": None,
                         "status": f"no episode #{epnum} here", "number": epnum, "anchored": anchored})
            continue

        season, epn = ep["season"], ep["episode"]
        fname = safe(f"{label} - S{season:02}E{epn:02} - {ep['title']}") + p.suffix.lower()
        if library_root:
            dest = Path(library_root) / safe(f"{label} [tmdbid-{show['id']}]") / f"Season {season:02}" / fname
        else:
            dest = p.with_name(fname)

        status = "OK (set)" if anchored else "OK"
        rt = ep.get("runtime")
        if rt and d and abs(d / 60 - rt) > max(3, rt * 0.15):
            status = f"CHECK: expected ~{rt}m"
        if dest.exists() and dest.resolve() != p.resolve():
            status = "CONFLICT: exists"
        if str(dest).lower() in used:
            status = "CONFLICT: duplicate"
        used.add(str(dest).lower())
        rows.append({"path": p, "duration": d, "include": True, "dest": dest, "status": status,
                     "number": epnum, "anchored": anchored})
    return rows
