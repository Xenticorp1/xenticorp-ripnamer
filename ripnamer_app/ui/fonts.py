"""Bundled brand fonts (Anton for display, Montserrat for text; both SIL OFL, see fonts/*-OFL.txt).

Loaded privately for this process before Tk starts, so nothing gets installed on the system.
If loading fails the theme falls back to system fonts."""

import ctypes
import ctypes.util
import glob
import os
import sys

from ..config import resource


def font_files() -> list[str]:
    return sorted(glob.glob(os.path.join(resource("fonts"), "*.ttf")))


def load_fonts() -> int:
    """Make the bundled fonts available to Tk. Call before tk.Tk(). Returns how many loaded."""
    files, loaded = font_files(), 0
    try:
        if sys.platform == "win32":
            FR_PRIVATE = 0x10
            add = ctypes.windll.gdi32.AddFontResourceExW
            loaded = sum(1 for f in files if add(f, FR_PRIVATE, 0) > 0)
        elif sys.platform.startswith("linux"):
            lib = ctypes.util.find_library("fontconfig")
            if lib:
                fc = ctypes.CDLL(lib)
                fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                loaded = sum(1 for f in files if fc.FcConfigAppFontAddFile(None, os.fsencode(f)))
    except Exception:
        pass
    return loaded
