"""Settings file, optional baked-in TMDb key, and bundled resource lookup."""

import json
import os
import sys
from pathlib import Path

from . import APP

# Optional key baked in at build time (build.bat / build.sh write ripnamer_key.py next to ripnamer.py).
try:
    from ripnamer_key import KEY as BAKED_KEY  # type: ignore
except ImportError:
    BAKED_KEY = ""


def config_path() -> Path:
    """%APPDATA%/RipNamer/config.json on Windows, ~/.config/RipNamer/config.json elsewhere."""
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    p = Path(base) / APP
    p.mkdir(parents=True, exist_ok=True)
    return p / "config.json"


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def resource(name: str) -> str:
    """Path to a file bundled next to the app (PyInstaller unpack dir, or the source folder)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)
