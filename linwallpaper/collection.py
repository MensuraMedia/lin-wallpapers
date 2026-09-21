"""The wallpaper library — a gi-free service over a small JSON index.

Owns the user's curated set of wallpapers. Stores *references* (absolute paths)
plus an always-present, non-removable **built-in default** that ships inside the
package, so the Wallpaper page is never empty. Originals are never copied, moved
or modified (the one shipped default is the sole in-package asset).

No ``gi`` here: this is service-layer and unit-testable against a temp dir.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import imaging

# The built-in default that ships with the app (EXIF-stripped at build time).
_BUILTIN = Path(__file__).parent / "data" / "wallpapers" / "default-graphite-wood.jpg"
_BUILTIN_NAME = "Default"

# Static extension allowlist used only to pre-filter a folder scan (keeps us from
# PIL-opening every file in a directory). A single explicitly-picked file is
# validated regardless of its extension. Kept static so this module stays gi-free
# (``imaging.supported_formats`` would pull in GdkPixbuf).
_IMAGE_EXTS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff",
     ".avif", ".heic", ".heif", ".jxl", ".svg", ".ico", ".ppm", ".pgm"}
)


def _default_data_dir() -> Path:
    """``$XDG_DATA_HOME/linwallpaper`` (or ``~/.local/share/linwallpaper``)."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "linwallpaper"


@dataclass(frozen=True)
class Item:
    """One library entry (the built-in default, or a referenced file)."""

    path: str
    name: str
    builtin: bool = False
    added: str | None = None

    @property
    def removable(self) -> bool:
        return not self.builtin

    @property
    def exists(self) -> bool:
        try:
            return Path(self.path).is_file()
        except OSError:
            return False


@dataclass
class AddResult:
    """Outcome of :meth:`Collection.add_paths` — for a user-facing summary."""

    added: int = 0
    skipped: int = 0
    dirs_scanned: int = 0
    added_paths: list[str] = field(default_factory=list)


class Collection:
    """The wallpaper library, backed by ``collection.json``."""

    def __init__(self, data_dir: str | os.PathLike | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _default_data_dir()
        self._index_file = self._data_dir / "collection.json"
        self._paths: list[dict] = self._load()

    # ---- read -------------------------------------------------------------
    @property
    def index_path(self) -> Path:
        return self._index_file

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def reload(self) -> None:
        """Re-read the index from disk (e.g. after the add-CLI wrote to it)."""
        self._paths = self._load()

    def items(self) -> list[Item]:
        """The built-in default first, then referenced files in add order."""
        out: list[Item] = []
        if _BUILTIN.is_file():
            out.append(Item(path=str(_BUILTIN), name=_BUILTIN_NAME, builtin=True))
        for entry in self._paths:
            p = entry["path"]
            out.append(Item(path=p, name=Path(p).name, added=entry.get("added")))
        return out

    def contains(self, path: str | os.PathLike) -> bool:
        return self._norm(path) in {e["path"] for e in self._paths}

    # ---- write ------------------------------------------------------------
    def add_paths(self, paths) -> AddResult:
        """Add files and/or directories. Returns a summary (added/skipped/dirs).

        A directory contributes every supported image *directly inside it*
        (non-recursive). Non-image or unreadable files are skipped. Duplicates
        (by real path) are skipped. The originals are never touched.
        """
        result = AddResult()
        known = {e["path"] for e in self._paths}
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                result.dirs_scanned += 1
                for child in self._scan_dir(p):
                    self._try_add(child, known, result)
            else:
                self._try_add(p, known, result)
        if result.added:
            self._save()
        return result

    def remove(self, path: str | os.PathLike) -> bool:
        """Drop a referenced file from the library (built-in cannot be removed)."""
        norm = self._norm(path)
        before = len(self._paths)
        self._paths = [e for e in self._paths if e["path"] != norm]
        if len(self._paths) != before:
            self._save()
            return True
        return False

    # ---- internals --------------------------------------------------------
    def _try_add(self, p: Path, known: set[str], result: AddResult) -> None:
        norm = self._norm(p)
        if norm in known:
            result.skipped += 1
            return
        ok, _reason = imaging.validate(norm)
        if not ok:
            result.skipped += 1
            return
        entry = {"path": norm, "added": datetime.now(UTC).isoformat(timespec="seconds")}
        self._paths.append(entry)
        known.add(norm)
        result.added += 1
        result.added_paths.append(norm)

    def _scan_dir(self, d: Path) -> list[Path]:
        try:
            children = sorted(d.iterdir())
        except OSError:
            return []
        return [c for c in children if c.is_file() and c.suffix.lower() in _IMAGE_EXTS]

    @staticmethod
    def _norm(path: str | os.PathLike) -> str:
        try:
            return str(Path(path).expanduser().resolve())
        except OSError:
            return str(path)

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for entry in items:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                path = entry["path"]
                if path not in seen:
                    seen.add(path)
                    out.append({"path": path, "added": entry.get("added")})
        return out

    def _save(self) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "items": self._paths}
            tmp = self._index_file.with_name(self._index_file.name + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._index_file)
        except OSError:
            pass
