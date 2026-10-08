"""Video file discovery and duration reading.

Durations are read natively (only a few KB of each file), so no FFmpeg/MKVToolNix is needed.
ffprobe / mkvmerge are used as a fallback only if they happen to be on PATH.
"""

import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = (".mkv", ".mp4", ".m4v")

# ----------------------------------------------------------------------------- MKV (EBML)

_ID_EBML = 0x1A45DFA3
_ID_SEGMENT = 0x18538067
_ID_INFO = 0x1549A966
_ID_TIMESCALE = 0x2AD7B1
_ID_DURATION = 0x4489
_ID_CLUSTER = 0x1F43B675


def _read_vint(f, keep_marker: bool) -> int:
    """EBML variable-length int. keep_marker=True for element IDs, False for sizes (-1 = unknown)."""
    b = f.read(1)
    if not b:
        raise EOFError
    first, length, mask = b[0], 1, 0x80
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError("bad vint")
    value = first if keep_marker else (first & (mask - 1))
    rest = f.read(length - 1)
    if len(rest) != length - 1:
        raise EOFError
    all_ones = (first & (mask - 1)) == (mask - 1) and all(x == 0xFF for x in rest)
    for x in rest:
        value = (value << 8) | x
    return -1 if (not keep_marker and all_ones) else value


def mkv_duration(path) -> float | None:
    with open(path, "rb") as f:
        if _read_vint(f, True) != _ID_EBML:
            return None
        f.seek(_read_vint(f, False), 1)
        if _read_vint(f, True) != _ID_SEGMENT:
            return None
        _read_vint(f, False)  # segment size (often "unknown")
        for _ in range(64):  # Segment Info is always near the start
            eid, size = _read_vint(f, True), _read_vint(f, False)
            if eid == _ID_INFO:
                end, scale, dur = f.tell() + size, 1_000_000, None
                while f.tell() < end:
                    cid, csize = _read_vint(f, True), _read_vint(f, False)
                    data = f.read(csize)
                    if cid == _ID_TIMESCALE:
                        scale = int.from_bytes(data, "big")
                    elif cid == _ID_DURATION:
                        dur = struct.unpack(">f" if csize == 4 else ">d", data)[0]
                return dur * scale / 1e9 if dur is not None else None
            if eid == _ID_CLUSTER or size < 0:
                return None
            f.seek(size, 1)
    return None

# ----------------------------------------------------------------------------- MP4 (atoms)


def mp4_duration(path) -> float | None:
    """Walk atoms to moov/mvhd. Works whether moov is at the start (faststart) or the end."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        end = f.tell()
        f.seek(0)

        def atoms(stop):
            while f.tell() + 8 <= stop:
                start = f.tell()
                size, kind = struct.unpack(">I4s", f.read(8))
                header = 8
                if size == 1:
                    size, header = struct.unpack(">Q", f.read(8))[0], 16
                elif size == 0:
                    size = stop - start
                if size < header:
                    return
                yield kind, start + header, start + size
                f.seek(start + size)

        for kind, body, stop in atoms(end):
            if kind != b"moov":
                continue
            f.seek(body)
            for k2, b2, _ in atoms(stop):
                if k2 == b"mvhd":
                    f.seek(b2)
                    version = f.read(1)[0]
                    f.read(3)
                    if version == 1:
                        f.read(16)
                        scale, dur = struct.unpack(">IQ", f.read(12))
                    else:
                        f.read(8)
                        scale, dur = struct.unpack(">II", f.read(8))
                    return dur / scale if scale else None
            return None
    return None

# ----------------------------------------------------------------------------- public API


def _run_quiet(cmd):
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw)


def duration(path) -> float | None:
    """Duration in seconds for .mkv/.mp4/.m4v, or None if it can't be read."""
    try:
        reader = mp4_duration if Path(path).suffix.lower() in (".mp4", ".m4v") else mkv_duration
        d = reader(path)
        if d:
            return d
    except Exception:
        pass
    if shutil.which("ffprobe"):
        try:
            r = _run_quiet(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(path)])
            return float(r.stdout.strip())
        except Exception:
            pass
    if shutil.which("mkvmerge"):
        try:
            r = _run_quiet(["mkvmerge", "-J", str(path)])
            return json.loads(r.stdout)["container"]["properties"]["duration"] / 1e9
        except Exception:
            pass
    return None


def natural_key(s: str):
    """Sort key so title_t2 < title_t10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def list_videos(folder) -> list[Path]:
    return sorted((p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS),
                  key=lambda p: natural_key(p.name))


def scan_folder(folder) -> list[dict]:
    return [{"path": p, "duration": duration(p)} for p in list_videos(folder)]


def fmt_dur(sec) -> str:
    if sec is None:
        return "?"
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
