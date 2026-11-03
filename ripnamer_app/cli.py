"""Headless commands (no Tk): plan a disc's names as JSON, then apply a clean plan.

    python3 -m ripnamer_app.cli plan FOLDER (--show-id N | --disc-name TEXT) [--season S]
        [--start-episode E] [--min-minutes M] [--specials] [--key-file PATH]
    python3 -m ripnamer_app.cli apply FOLDER --plan PLAN.json --dest DIR

Each prints one JSON object on stdout. Exit codes: 0 clean / done, 3 plan not clean, 2 bad arguments,
1 any other error ({"ok": false, "error": "..."}). The TMDb key comes from --key-file or the
RIPNAMER_TMDB_KEY environment variable; without one it's an error, never a guess.

plan uses the Continuous timeline from S<season>E<start> (specials only with --specials), Auto episode
length, 25% tolerance, no maximum, and leaves already-named files alone, i.e. planner.plan with the
desktop app's defaults. apply moves with mover.execute: undo log in FOLDER, never overwrites.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from . import media, mover, planner, tmdb
from .discs import match_show, parse_disc_name

PLAN_VERSION = 1
EXIT_OK, EXIT_ERROR, EXIT_ARGS, EXIT_NOT_CLEAN = 0, 1, 2, 3
TOLERANCE = 0.25
KEY_ENV = "RIPNAMER_TMDB_KEY"
EXTRA = "skip: extra (short)"   # the only skip a clean plan may have: shorter than --min-minutes


class BadArgs(Exception):
    """Exit 2."""


class Failed(Exception):
    """Exit 1."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BadArgs(message)


def _parser():
    p = _Parser(prog="python3 -m ripnamer_app.cli", description="Xenticorp Ripnamer headless commands.")
    sub = p.add_subparsers(dest="command", required=True)
    pl = sub.add_parser("plan", help="plan the names for one disc's rips (prints JSON)")
    pl.add_argument("folder")
    which = pl.add_mutually_exclusive_group(required=True)
    which.add_argument("--show-id", type=int, help="TMDb show id")
    which.add_argument("--disc-name", help='disc label, e.g. "Show - Season 2 - Disc 1"')
    pl.add_argument("--season", type=int, help="season of the first episode (default: from --disc-name)")
    pl.add_argument("--start-episode", type=int, default=1, help="first episode on the disc (default 1)")
    pl.add_argument("--min-minutes", type=float, default=5, help="files shorter than this are extras (default 5)")
    pl.add_argument("--specials", action="store_true", help="put dated specials in the timeline")
    pl.add_argument("--key-file", help=f"file holding the TMDb key (default: ${KEY_ENV})")
    pl.set_defaults(func=cmd_plan)
    ap = sub.add_parser("apply", help="move the files of a clean plan into a library folder")
    ap.add_argument("folder")
    ap.add_argument("--plan", required=True, help="the JSON that plan printed")
    ap.add_argument("--dest", required=True, help="library root (must exist)")
    ap.set_defaults(func=cmd_apply)
    return p


def read_key(key_file):
    if key_file:
        try:
            key = Path(key_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as e:
            raise Failed(f"Can't read the key file: {getattr(e, 'strerror', None) or e}") from None
    else:
        key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise Failed(f"No TMDb key: pass --key-file PATH or set {KEY_ENV}.")
    return key

# ----------------------------------------------------------------------------- plan


def problems(rows) -> list[str]:
    """Why a plan isn't clean ([] = clean): every file included with an OK name or skipped as a short
    extra, and at least one file named."""
    out = []
    for r in rows:
        if r["include"] and not (r["dest"] and r["status"].startswith("OK")):
            out.append(f"{r['file']}: {r['status']}")
        elif not r["include"] and r["status"] != EXTRA:
            out.append(f"{r['file']}: {r['status']}")
    if not any(r["include"] and r["dest"] for r in rows):
        out.append("No file to name." if rows else "No .mkv or .mp4 files in the folder.")
    return out


def build_plan(client, folder, show, season, start=1, min_minutes=5, specials=False) -> dict:
    """The plan JSON for one folder. client: a tmdb.TMDb (injectable for tests)."""
    timeline = client.timeline(show["id"], include_specials=specials)
    number = tmdb.position(timeline, season, start)
    if number is None:
        raise Failed(f"S{season:02}E{start:02} isn't in the TMDb timeline for {planner.show_label(show)}"
                     + ("." if specials else " (specials are off)."))
    by_num = {e["number"]: e for e in timeline}
    files = media.scan_folder(folder)
    rows, last = [], None
    with tempfile.TemporaryDirectory() as root:  # empty stand-in library: dest comes out relative to it
        for r in planner.plan(files, timeline, show, number, min_minutes, {}, library_root=root,
                              ep_length=None, tolerance=TOLERANCE, max_minutes=0, leave_named=True):
            ep = by_num[r["number"]] if r["dest"] is not None else None
            d = r["duration"]
            rows.append({"file": r["path"].name, "size": r["path"].stat().st_size,
                         "seconds": round(d, 3) if d is not None else None,
                         "include": r["include"], "status": r["status"],
                         "season": ep and ep["season"], "episode": ep and ep["episode"],
                         "title": ep and ep["title"],
                         "dest": Path(r["dest"]).relative_to(root).as_posix() if ep else None})
            if ep and r["include"] and (last is None or r["number"] > last[0]):
                last = (r["number"], {"season": ep["season"], "episode": ep["episode"]})
    reasons = problems(rows)
    return {"v": PLAN_VERSION, "ok": True, "clean": not reasons, "reasons": reasons,
            "show": {"id": show["id"], "name": show["name"], "year": show["year"]},
            "season": season, "start": start, "rows": rows, "last": last and last[1]}


def cmd_plan(args, client_factory):
    folder = Path(args.folder)
    if not folder.is_dir():
        raise BadArgs(f"Not a folder: {args.folder}")
    if args.start_episode < 1 or (args.season is not None and args.season < 0) or args.min_minutes < 0:
        raise BadArgs("--season must be 0 or more, --start-episode 1 or more, --min-minutes 0 or more.")
    disc = None
    if args.disc_name is not None:
        disc = parse_disc_name(args.disc_name)
        if not disc or not disc["show"]:
            raise BadArgs(f'Can\'t read a show, season and disc from "{args.disc_name}".')
    season = args.season if args.season is not None else disc and disc["season"]
    if season is None:
        raise BadArgs("--season is needed with --show-id.")
    client = client_factory(read_key(args.key_file))
    if disc:
        show, why = match_show(client, disc["show"], season)
        if show is None:
            raise Failed(why)
    else:
        show = client.show_info(args.show_id)
    out = build_plan(client, folder, show, season, args.start_episode, args.min_minutes, args.specials)
    return out, EXIT_OK if out["clean"] else EXIT_NOT_CLEAN

# ----------------------------------------------------------------------------- apply


def _control(s: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in s)


def dest_problem(dest):
    """None if dest is a relative 'Show (Year) [tmdbid-X]/Season NN/<file>' path, else what's wrong."""
    if not isinstance(dest, str) or not dest:
        return "no dest"
    if _control(dest):
        return "control character in dest"
    if "\\" in dest or ":" in dest or dest.startswith("/") or Path(dest).is_absolute():
        return "dest is not a plain relative path"
    parts = dest.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return "dest has an empty, . or .. part"
    if len(parts) != 3 or not re.fullmatch(r"Season \d{2,}", parts[1]):
        return "dest is not Show/Season NN/file"
    return None


def check_plan(plan, folder: Path, root: Path):
    """(mover rows, refusals). Refuses unless the plan is clean, every file in it still exists with the
    same size, and no dest exists already or leaves root."""
    if not isinstance(plan, dict) or plan.get("v") != PLAN_VERSION or plan.get("ok") is not True:
        return [], ["Not a version 1 plan from 'plan'."]
    if plan.get("clean") is not True:
        return [], ["The plan is not clean."] + [str(x) for x in plan.get("reasons") or []]
    rows = plan.get("rows")
    if not isinstance(rows, list) or not rows:
        return [], ["The plan has no rows."]
    base, todo, refusals, names, dests = root.resolve(), [], [], set(), set()
    for r in rows:
        name = r.get("file") if isinstance(r, dict) else None
        if (not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\\" in name
                or _control(name) or name in names):
            refusals.append(f"Bad file name in plan: {name!r}")
            continue
        names.add(name)
        src = folder / name
        try:
            size = src.stat().st_size if src.is_file() else None
        except OSError:
            size = None
        if size is None:
            refusals.append(f"{name}: missing")
        elif size != r.get("size"):
            refusals.append(f"{name}: changed since the plan (size {size}, plan says {r.get('size')})")
        if not r.get("include"):
            if r.get("status") != EXTRA:
                refusals.append(f"{name}: skipped but not as an extra ({r.get('status')})")
            continue
        status, dest = r.get("status"), r.get("dest")
        if not (isinstance(status, str) and status.startswith("OK")):
            refusals.append(f"{name}: status {status!r}")
            continue
        why = dest_problem(dest)
        if why:
            refusals.append(f"{name}: {why}: {dest!r}")
            continue
        target = root / dest
        if not target.resolve().is_relative_to(base):
            refusals.append(f"{name}: dest leaves the library folder: {dest}")
        elif os.path.lexists(target):
            refusals.append(f"{name}: already exists: {dest}")
        elif dest.casefold() in dests:
            refusals.append(f"{name}: two files with the same dest: {dest}")
        dests.add(dest.casefold())
        todo.append({"path": src, "dest": target, "include": True, "status": status})
    if not todo and not refusals:
        refusals.append("Nothing to move.")
    return todo, refusals


def cmd_apply(args, client_factory=None):
    folder, root = Path(args.folder), Path(args.dest)
    if not folder.is_dir():
        raise BadArgs(f"Not a folder: {args.folder}")
    if not root.is_dir():
        raise BadArgs(f"Library folder doesn't exist: {args.dest}")
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise Failed(f"Can't read the plan: {getattr(e, 'strerror', None) or e}") from None
    todo, refusals = check_plan(plan, folder, root)
    if refusals:
        return {"v": PLAN_VERSION, "ok": False, "error": "Refused: " + refusals[0], "moved": 0, "log": None,
                "errors": refusals}, EXIT_ERROR
    moved, log, errors, cancelled = mover.execute(todo, folder)
    ok = not errors and not cancelled and moved == len(todo)
    return {"v": PLAN_VERSION, "ok": ok, "moved": moved, "log": str(log) if log else None,
            "errors": errors}, EXIT_OK if ok else EXIT_ERROR

# ----------------------------------------------------------------------------- entry points


def run(argv=None, client_factory=None, out=None) -> int:
    """Parse argv, run the command, print one JSON object to out, return the exit code.
    client_factory(key) -> tmdb.TMDb; tests pass a fake so nothing touches the network."""
    out = out or sys.stdout
    factory = client_factory or tmdb.TMDb
    command = None
    try:
        args = _parser().parse_args(argv)
        command = args.command
        result, code = args.func(args, factory)
    except BadArgs as e:
        result, code = {"v": PLAN_VERSION, "ok": False, "error": str(e)}, EXIT_ARGS
    except (Failed, tmdb.TMDbError) as e:
        result, code = {"v": PLAN_VERSION, "ok": False, "error": str(e)}, EXIT_ERROR
    except Exception as e:  # never a traceback instead of JSON
        result, code = {"v": PLAN_VERSION, "ok": False, "error": f"Unexpected error: {e}"}, EXIT_ERROR
    if command == "apply" and "moved" not in result:
        result.update(moved=0, log=None, errors=[result["error"]])
    out.write(json.dumps(result) + "\n")
    out.flush()
    return code


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
