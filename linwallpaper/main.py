"""LinWallpaper entry point — Adw.Application, one window, one-shot."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import APP_ID  # noqa: E402
from .ui.window import AppWindow  # noqa: E402

_CSS = Path(__file__).with_name("ui") / "style.css"


class LinWallpaperApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._window: AppWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._load_css()

    def do_activate(self) -> None:
        if self._window is None:
            self._window = AppWindow(self)
        self._window.present()

    def _load_css(self) -> None:
        if not _CSS.exists():
            return
        provider = Gtk.CssProvider()
        provider.load_from_path(str(_CSS))
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )


def main(argv: list[str] | None = None) -> int:
    app = LinWallpaperApp()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
