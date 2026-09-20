"""Filesystem locations. Pure ``pathlib`` — importable from every layer."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESOURCES_DIR = PROJECT_ROOT / "resources"
CSS_DIR = RESOURCES_DIR / "css"
BUILD_DIR = PROJECT_ROOT / "build"

GRESOURCE_FILE = BUILD_DIR / "lin-wallpapers.gresource"
GRESOURCE_PREFIX = "/io/mensuramedia/LinWallpapers"
SCHEMA_DIR = BUILD_DIR / "schemas"

_APP_DIR = "lin-wallpapers"


def _xdg(variable: str, fallback: str) -> Path:
    """``$variable`` when set to an absolute path (the XDG spec says to ignore anything else)."""
    value = os.environ.get(variable)
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback


def data_dir() -> Path:
    """Catalogue and backups (from M1): ``~/.local/share/lin-wallpapers``."""
    return _xdg("XDG_DATA_HOME", ".local/share") / _APP_DIR


def catalogue_db() -> Path:
    """The SQLite catalogue (M1): ``<data_dir>/catalogue.db``."""
    return data_dir() / "catalogue.db"


def cache_dir() -> Path:
    """Thumbnails (from M1): ``~/.cache/lin-wallpapers``."""
    return _xdg("XDG_CACHE_HOME", ".cache") / _APP_DIR


def thumbs_dir() -> Path:
    """The thumbnail cache (M1): ``<cache_dir>/thumbnails``."""
    return cache_dir() / "thumbnails"


def state_dir() -> Path:
    """Activity log (from M6): ``~/.local/state/lin-wallpapers``."""
    return _xdg("XDG_STATE_HOME", ".local/state") / _APP_DIR
