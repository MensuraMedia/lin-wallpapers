"""Helpers shared by the catalogue tests (no tests of its own). Databases live under ``tmp_path`` only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.catalogue import db
from src.scanner.displays import Display, DisplayDetection, DisplaySource

FHD = Display("eDP-1", 1920, 1080, primary=True, source=DisplaySource.DRM)
UHD = Display("HDMI-A-1", 3840, 2160, source=DisplaySource.DRM)
PORTRAIT = Display("DP-2", 1080, 1920, source=DisplaySource.XRANDR)


def open_db(tmp_path: Path, name: str = "catalogue.db") -> sqlite3.Connection:
    assert "/.local/share/" not in str(tmp_path)
    return db.open_catalogue(tmp_path / "data" / name)


def db_path(tmp_path: Path, name: str = "catalogue.db") -> Path:
    return tmp_path / "data" / name


def detection(*displays: Display) -> DisplayDetection:
    return DisplayDetection(displays=tuple(displays), attempts=(), reason=None)


def set_displays(conn: sqlite3.Connection, *displays: Display, now: int = 1000) -> list[int]:
    ids, _changed = db.save_display_snapshot(conn, detection(*displays), now)
    return ids


def add_image(
    conn: sqlite3.Connection, path: str, width: int | None = 1920, height: int | None = 1080, **cols: object
) -> int:
    directory, _, name = path.rpartition("/")
    values: dict[str, object] = {
        "path": path,
        "dir": directory or "/",
        "name": name,
        "width": width,
        "height": height,
        "format": "JPEG",
        "size": 500_000,
        "first_seen": 100,
        **cols,
    }
    columns = ", ".join(values)  # column names come from this test helper only, never from test data
    marks = ", ".join("?" for _ in values)
    cursor = conn.execute(f"INSERT INTO image({columns}) VALUES ({marks})", tuple(values.values()))
    assert cursor.lastrowid is not None
    return cursor.lastrowid
