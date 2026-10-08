"""Executes a rename plan and undoes it.

Same drive  -> instant os.rename.
Other drive -> chunked copy with live progress, free-space check, copy to '<name>.ripnamer-part'
               then swap into place, verify size, delete the original. Cancel is honoured
               between chunks; a cancelled copy leaves the original untouched and no partial file.

The undo log is rewritten after every successful move, so it's valid even after a crash or cancel.
"""

import errno
import json
import os
import shutil
import threading
import time
from pathlib import Path

from .planner import is_ready

CHUNK = 8 * 1024 * 1024          # 8 MB copy blocks
SPACE_MARGIN = 64 * 1024 * 1024  # keep 64 MB spare on the target drive
PART_SUFFIX = ".ripnamer-part"


class Cancelled(Exception):
    pass


class Progress:
    """Written by the worker thread, polled by the UI. Plain attributes; reads are best-effort."""

    def __init__(self):
        self.lock = threading.Lock()
        self.index = 0            # 1-based file being processed
        self.count = 0            # total files
        self.name = ""            # current file name
        self.copying = False      # True while doing a cross-drive copy
        self.file_done = 0
        self.file_total = 0
        self.bytes_done = 0       # overall
        self.bytes_total = 0
        self.started = time.monotonic()

    def begin_file(self, index, name, size):
        with self.lock:
            self.index, self.name = index, name
            self.file_done, self.file_total, self.copying = 0, size, False

    def advance(self, n):
        with self.lock:
            self.file_done += n
            self.bytes_done += n

    def snapshot(self) -> dict:
        with self.lock:
            elapsed = max(time.monotonic() - self.started, 1e-6)
            return {"index": self.index, "count": self.count, "name": self.name, "copying": self.copying,
                    "file_done": self.file_done, "file_total": self.file_total,
                    "bytes_done": self.bytes_done, "bytes_total": self.bytes_total,
                    "rate": self.bytes_done / elapsed}


def _cross_device(e: OSError) -> bool:
    return e.errno == errno.EXDEV or getattr(e, "winerror", None) == 17  # ERROR_NOT_SAME_DEVICE


def _size(p) -> int:
    try:
        return Path(p).stat().st_size
    except OSError:
        return 0


def move_file(src, dst, prog: Progress | None = None, cancel: threading.Event | None = None) -> str:
    """Move one file. Returns 'renamed', 'copied', or 'copied-kept-source' (original couldn't be deleted)."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"already exists: {dst.name}")
    size = _size(src)
    try:
        os.rename(src, dst)
        if prog:
            prog.advance(size)
        return "renamed"
    except OSError as e:
        if not _cross_device(e):
            raise

    free = shutil.disk_usage(dst.parent).free
    if free < size + SPACE_MARGIN:
        raise OSError(f"not enough space on target drive (needs {size / 2**30:.1f} GB, "
                      f"{free / 2**30:.1f} GB free)")
    if prog:
        prog.copying = True
    part = dst.with_name(dst.name + PART_SUFFIX)
    try:
        with open(src, "rb") as fi, open(part, "wb") as fo:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled
                buf = fi.read(CHUNK)
                if not buf:
                    break
                fo.write(buf)
                if prog:
                    prog.advance(len(buf))
            fo.flush()
            os.fsync(fo.fileno())
        shutil.copystat(src, part)
        if _size(part) != size:
            raise OSError("copy verification failed (size mismatch)")
        os.replace(part, dst)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    try:
        os.remove(src)
    except OSError:
        return "copied-kept-source"
    return "copied"


def _write_log(log: Path, moves: list) -> None:
    tmp = log.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 2, "app": "Xenticorp Ripnamer", "moves": moves}, indent=2),
                   encoding="utf-8")
    os.replace(tmp, log)


def execute(rows, log_dir, prog: Progress | None = None, cancel: threading.Event | None = None):
    """Carry out every ready row. Returns (moved_count, log_path|None, errors, cancelled)."""
    prog = prog or Progress()
    todo = [r for r in rows if is_ready(r) and Path(r["path"]) != Path(r["dest"])]
    prog.count = len(todo)
    prog.bytes_total = sum(_size(r["path"]) for r in todo)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    log = Path(log_dir) / f"ripnamer_undo_{stamp}.json"
    n = 2
    while log.exists():  # two runs in the same second
        log = Path(log_dir) / f"ripnamer_undo_{stamp}_{n}.json"
        n += 1
    moves, errors, cancelled = [], [], False

    for i, r in enumerate(todo, 1):
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        src, dst = Path(r["path"]), Path(r["dest"])
        prog.begin_file(i, src.name, _size(src))
        try:
            how = move_file(src, dst, prog, cancel)
            moves.append([str(src), str(dst)])
            if how == "copied-kept-source":
                errors.append(f"{src.name}: copied, but the original couldn't be deleted")
            try:
                _write_log(log, moves)
            except OSError as e:
                errors.append(f"could not write undo log: {e}")
        except Cancelled:
            cancelled = True
            break
        except Exception as e:
            errors.append(f"{src.name}: {e}")
    return len(moves), (log if moves and log.exists() else None), errors, cancelled


def undo(log_path, prog: Progress | None = None, cancel: threading.Event | None = None):
    """Reverse a log. Returns (restored_count, errors, cancelled).
    A fully undone log is renamed *.undone.json; a partial one is trimmed so undo can be re-run."""
    prog = prog or Progress()
    log_path = Path(log_path)
    moves = json.loads(log_path.read_text(encoding="utf-8"))["moves"]
    pending = list(reversed(moves))
    prog.count = len(pending)
    prog.bytes_total = sum(_size(dst) for _, dst in pending)
    restored, errors, cancelled, left = 0, [], False, []

    for i, (src, dst) in enumerate(pending, 1):
        if cancelled or (cancel is not None and cancel.is_set()):
            cancelled = True
            left.append([src, dst])
            continue
        prog.begin_file(i, Path(dst).name, _size(dst))
        try:
            if Path(src).exists():
                # Original was left behind by a copy that couldn't delete it: just drop the copy.
                if Path(dst).exists() and _size(src) == _size(dst):
                    os.remove(dst)
                    prog.advance(_size(src))
                else:
                    raise FileExistsError(f"original name already in use: {Path(src).name}")
            else:
                move_file(dst, src, prog, cancel)
            restored += 1
            for parent in (Path(dst).parent, Path(dst).parent.parent):  # tidy empty Season/Show dirs
                try:
                    parent.rmdir()
                except OSError:
                    pass
        except Cancelled:
            cancelled = True
            left.append([src, dst])
        except Exception as e:
            errors.append(f"{Path(dst).name}: {e}")
            left.append([src, dst])

    if left:
        _write_log(log_path, list(reversed(left)))
    else:
        log_path.rename(log_path.with_suffix(".undone.json"))
    return restored, errors, cancelled
