"""Lin Wallpapers — application entry point and composition root (M1 §2.9, ruling Q14).

A single-instance ``Gtk.Application``: a window you open to change a wallpaper. On activation it builds the
one :class:`AppServices` (catalogue writer + read connections + scan service), constructs the view models
once and injects them into the pages through a :class:`PageContext`. Closing the window cancels any scan
and calls ``services.close()`` — the writer and worker pool are joined, so nothing is left running.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from src import APP_ID
from src.catalogue.db import get_setting, set_setting
from src.config import config_paths
from src.config.config_themes import DEFAULT_THEME, get_theme
from src.gtk_version import Gio, Gtk
from src.modules.manager_navigation import NavigationManager
from src.modules.manager_theme_applicator import ThemeApplicator
from src.pages import PageContext
from src.scanner.displays import service_probes
from src.ui import compat
from src.ui.dashboard_window import DashboardWindow
from src.ui.sidebar import NAV_ITEMS
from src.util import threads
from src.util.glib_loop import glib_scheduler
from src.viewmodels import browse_vm as browse_module
from src.viewmodels.browse_vm import BrowseVM
from src.viewmodels.gdk_displays import GdkDisplayProbe
from src.viewmodels.scan_vm import ScanVM
from src.viewmodels.services import AppServices
from src.viewmodels.sources_vm import SourcesVM


class LinWallpapersApp(Gtk.Application):  # type: ignore[misc]
    def __init__(self, application_id: str = APP_ID, flags: Any = Gio.ApplicationFlags.FLAGS_NONE) -> None:
        super().__init__(application_id=application_id, flags=flags)
        self.window: DashboardWindow | None = None
        self.theme_applicator: ThemeApplicator | None = None
        self.services: AppServices | None = None
        self.scan_vm: ScanVM | None = None
        self.sources_vm: SourcesVM | None = None
        self.browse_vm: BrowseVM | None = None
        self.page_context: PageContext | None = None

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.theme_applicator = ThemeApplicator()
        self.theme_applicator.apply_theme(get_theme(DEFAULT_THEME))

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

        # F5 rescans; enabled once the scan view model exists (do_activate).
        rescan = Gio.SimpleAction.new("rescan", None)
        rescan.set_enabled(False)
        rescan.connect("activate", self.on_rescan)
        self.add_action(rescan)
        self.set_accels_for_action("app.rescan", ["F5"])

        for index, (_label, route, _icon) in enumerate(NAV_ITEMS, start=1):
            self.set_accels_for_action(f"win.navigate('{route}')", [f"<Primary>{index}"])

    def do_activate(self) -> None:
        if self.window is None:
            self._build_services()
            self.window = DashboardWindow(self, NavigationManager())
            compat.on_close_request(self.window, self.on_window_close)
            compat.show(self.window)
            self._land_on_start_page()
        self.window.present()

    def _build_services(self) -> None:
        probes = [GdkDisplayProbe(), *service_probes(Path("/"), os.environ)]
        self.services = AppServices(
            db_path=config_paths.catalogue_db(), scheduler=glib_scheduler, display_probes=probes
        )
        self.scan_vm = ScanVM(self.services)
        self.sources_vm = SourcesVM(self.services)
        self.browse_vm = BrowseVM(self.services)
        self.page_context = PageContext(
            scan_vm=self.scan_vm,
            sources_vm=self.sources_vm,
            browse_vm=self.browse_vm,
            segment=browse_module.Segment,
            orientation=browse_module.Orientation,
            aspect=browse_module.AspectBucket,
            sort=browse_module.Sort,
        )
        rescan = self.lookup_action("rescan")
        if rescan is not None:
            rescan.set_enabled(True)

    def _land_on_start_page(self) -> None:
        """Acceptance #4: the *first* run opens on Browse when the catalogue holds images, else on the
        Sources scan hero. Every later run honours the remembered route (``window_state`` restored it), so
        this steers only that first launch — tracked by the catalogue's ``first_run_done`` flag."""
        if self.window is None or self.services is None:
            return
        if not self._first_run():
            return
        route = "browse" if self._has_images() else "sources"
        self.window.content_area.show_page(route)
        self.services.writer.submit(lambda conn: set_setting(conn, "first_run_done", True))

    def _first_run(self) -> bool:
        if self.services is None:
            return False
        try:
            return not bool(get_setting(self.services.read(), "first_run_done", False))
        except Exception:
            return False

    def _has_images(self) -> bool:
        if self.services is None:
            return False
        try:
            conn = self.services.read()
            row = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM image WHERE missing = 0 AND excluded_by IS NULL)"
            ).fetchone()
            return bool(row[0])
        except Exception:
            return False

    def on_rescan(self, *_args: Any) -> None:
        if self.scan_vm is not None:
            self.scan_vm.start()

    def on_window_close(self) -> None:
        if self.window is not None:
            self.window.save_state()
        if self.scan_vm is not None:
            self.scan_vm.cancel()

    def on_quit(self, *_args: Any) -> None:
        """Ctrl+Q: ``quit()`` emits no close request, so the state is saved here, while the window exists."""
        self.on_window_close()
        self.quit()

    def do_shutdown(self) -> None:
        # Nothing runs in the background: cancel any scan, drop the feed subscription, join the writer + pool.
        if self.scan_vm is not None:
            self.scan_vm.cancel()
        if self.browse_vm is not None:
            self.browse_vm.close()
        if self.services is not None:
            self.services.close()
        else:
            threads.shutdown(wait=False)
        Gtk.Application.do_shutdown(self)


def main(argv: list[str] | None = None) -> int:
    return int(LinWallpapersApp().run(sys.argv if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
