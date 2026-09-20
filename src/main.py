"""Lin Wallpapers — application entry point.

A single-instance ``Gtk.Application``: a window you open to change a wallpaper. Closing it
leaves nothing running.
"""

from __future__ import annotations

import sys
from typing import Any

from src import APP_ID
from src.config.config_themes import DEFAULT_THEME, get_theme
from src.gtk_version import Gio, Gtk
from src.modules.manager_navigation import NavigationManager
from src.modules.manager_theme_applicator import ThemeApplicator
from src.ui import compat
from src.ui.dashboard_window import DashboardWindow
from src.ui.sidebar import NAV_ITEMS
from src.util import threads


class LinWallpapersApp(Gtk.Application):  # type: ignore[misc]
    def __init__(self, application_id: str = APP_ID, flags: Any = Gio.ApplicationFlags.FLAGS_NONE) -> None:
        super().__init__(application_id=application_id, flags=flags)
        self.window: DashboardWindow | None = None
        self.theme_applicator: ThemeApplicator | None = None

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.theme_applicator = ThemeApplicator()
        self.theme_applicator.apply_theme(get_theme(DEFAULT_THEME))

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

        # F5 is reserved for rescan (M1): registered now so nothing else claims it.
        rescan = Gio.SimpleAction.new("rescan", None)
        rescan.set_enabled(False)
        self.add_action(rescan)
        self.set_accels_for_action("app.rescan", ["F5"])

        for index, (_label, route, _icon) in enumerate(NAV_ITEMS, start=1):
            self.set_accels_for_action(f"win.navigate('{route}')", [f"<Primary>{index}"])

    def do_activate(self) -> None:
        if self.window is None:
            self.window = DashboardWindow(self, NavigationManager())
            compat.on_close_request(self.window, self.on_window_close)
            compat.show(self.window)
        self.window.present()

    def on_window_close(self) -> None:
        if self.window is not None:
            self.window.save_state()

    def on_quit(self, *_args: Any) -> None:
        """Ctrl+Q: ``quit()`` emits no close request, so the state is saved here, while the window exists."""
        self.on_window_close()
        self.quit()

    def do_shutdown(self) -> None:
        threads.shutdown(wait=False)  # closing the window leaves no worker thread behind
        Gtk.Application.do_shutdown(self)


def main(argv: list[str] | None = None) -> int:
    return int(LinWallpapersApp().run(sys.argv if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
