"""Window size and last route, remembered in GSettings (milestones M0.4).

Running from source, the schema is compiled into ``build/schemas`` by ``run.sh``; once packaged
it is found in the system schema directory. Without a schema nothing is persisted — the app
still runs, it just opens at the defaults.
"""

from __future__ import annotations

from typing import Any

from src import APP_ID
from src.config.config_paths import SCHEMA_DIR
from src.gtk_version import Gio, GLib


def _open_settings() -> Any:
    default = Gio.SettingsSchemaSource.get_default()
    source = default
    if (SCHEMA_DIR / "gschemas.compiled").exists():
        try:
            source = Gio.SettingsSchemaSource.new_from_directory(str(SCHEMA_DIR), default, False)
        except GLib.Error:
            source = default
    schema = source.lookup(APP_ID, True) if source is not None else None
    if schema is None:
        return None
    return Gio.Settings.new_full(schema, None, None)


class WindowState:
    """Thin wrapper so the window never touches ``Gio.Settings`` keys directly."""

    def __init__(self) -> None:
        self._settings = _open_settings()

    @property
    def persistent(self) -> bool:
        return self._settings is not None

    def size(self, default: tuple[int, int]) -> tuple[int, int]:
        if self._settings is None:
            return default
        return (self._settings.get_int("window-width"), self._settings.get_int("window-height"))

    def maximized(self) -> bool:
        return bool(self._settings is not None and self._settings.get_boolean("window-maximized"))

    def last_route(self, default: str) -> str:
        if self._settings is None:
            return default
        return str(self._settings.get_string("last-route")) or default

    def save(
        self, width: int, height: int, maximized: bool, route: str | None, *, keep_size: bool = False
    ) -> None:
        """Remember the state; ``keep_size`` leaves the stored size alone (no usable size to store)."""
        if self._settings is None:
            return
        if not maximized and not keep_size:
            self._settings.set_int("window-width", width)
            self._settings.set_int("window-height", height)
        self._settings.set_boolean("window-maximized", maximized)
        if route:
            self._settings.set_string("last-route", route)
