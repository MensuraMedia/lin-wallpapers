"""Tiny gi-free settings store — ``settings.json`` under the config dir.

Holds small app preferences that must persist between runs (e.g. whether the
file-manager context-menu integration is enabled). Separate from ``applied.json``
(privileged last-applied images) so each file has one job.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "linwallpaper"


class Settings:
    """Load/store a flat dict of preferences, tolerant of a missing/corrupt file."""

    def __init__(self, config_dir: str | os.PathLike | None = None) -> None:
        self._config_dir = Path(config_dir) if config_dir else _default_config_dir()
        self._file = self._config_dir / "settings.json"
        self._data: dict = self._load()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    def _load(self) -> dict:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        try:
            self._config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            tmp = self._file.with_name(self._file.name + ".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self._file)
        except OSError:
            pass
