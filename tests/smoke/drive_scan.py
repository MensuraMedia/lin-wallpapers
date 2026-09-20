"""Drives a real scan end-to-end and proves the Browse grid fills (M1 acceptance #2).

Registers ``$LWP_SCAN_ROOT`` as a root, runs the real ``ScanVM``, waits for it to finish, then reads the
Browse view model: it prints one ``SCAN {json}`` line (all-count and a filtered count) and, given a
screenshot path, saves the populated page. Assertions live in ``test_browse_fills.py``.

    python -m tests.smoke.drive_scan [screenshot.png] [route]

Environment: ``LWP_SCAN_ROOT`` (required), plus an isolated ``XDG_DATA_HOME``/``XDG_CACHE_HOME`` so the
real catalogue is never touched. GTK 3 introspection is used freely — this is test code, not ported code.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

os.environ["GSETTINGS_BACKEND"] = "memory"

from src.catalogue.db import set_setting
from src.config.config_layout import Layout
from src.gtk_version import Gdk, Gio, GLib
from src.main import LinWallpapersApp
from src.viewmodels.browse_vm import Orientation


def main() -> int:
    scan_root = os.environ["LWP_SCAN_ROOT"]
    screenshot = sys.argv[1] if len(sys.argv) > 1 else None
    route = sys.argv[2] if len(sys.argv) > 2 else "browse"
    app = LinWallpapersApp("io.mensuramedia.LinWallpapers.Smoke", Gio.ApplicationFlags.NON_UNIQUE)
    result: dict[str, Any] = {}
    fired: set[str] = set()

    def once(tag: str) -> bool:
        if tag in fired:
            return False
        fired.add(tag)
        return True

    def begin() -> bool:
        # Show even the small fixtures: drop the default long-edge view filter's floor for this run.
        app.services.writer.submit(lambda c: set_setting(c, "scan.min_long_edge", 0)).result()
        app.sources_vm.add_root(scan_root, cb=lambda _snapshot: start_scan())
        return False

    def start_scan() -> None:
        app.scan_vm.add_observer(on_scan)
        app.scan_vm.start()

    def on_scan(state: Any) -> None:
        if not state.running and state.result is not None and once("scan"):
            result["scan_result"] = state.result
            result["ideal"] = state.ideal
            GLib.idle_add(load_all)

    def load_all() -> bool:
        app.browse_vm.refresh(cb=on_all)
        return False

    def on_all(state: Any) -> None:
        if not once("all"):
            return
        result["all_total"] = state.total
        result["all_cards"] = len(state.cards)
        app.window.unmaximize()
        app.window.resize(Layout.dimensions.WINDOW_DEFAULT_WIDTH, Layout.dimensions.WINDOW_DEFAULT_HEIGHT)
        app.window.content_area.show_page(route)
        GLib.timeout_add(900, shoot_then_filter)

    def shoot_then_filter() -> bool:
        if screenshot:
            gdk_window = app.window.get_window()
            width, height = gdk_window.get_width(), gdk_window.get_height()
            Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width, height).savev(screenshot, "png", [], [])
        app.browse_vm.set_orientation(Orientation.LANDSCAPE)
        GLib.timeout_add(500, capture_filtered)
        return False

    def capture_filtered() -> bool:
        result["filtered_total"] = app.browse_vm.state.total
        print("SCAN " + json.dumps(result))
        app.quit()
        return False

    app.connect("activate", lambda *_: GLib.timeout_add(250, begin))
    return int(app.run([]))


if __name__ == "__main__":
    sys.exit(main())
