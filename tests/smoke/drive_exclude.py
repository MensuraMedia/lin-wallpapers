"""Drives the Browse right-click *Exclude Image* path end-to-end in the running app (M1.7).

Scans ``$LWP_SCAN_ROOT``, fills Browse, then exercises ``BrowseVM.exclude_image`` on the first card and
its undo — the same methods the card's context menu calls. Prints one ``EXCL {json}`` line with the
before/after grid totals, the FILE-rule count while excluded, and the total after undo. Assertions live
in ``test_browse_exclude.py``.

    python -m tests.smoke.drive_exclude [screenshot.png]

Environment mirrors ``drive_scan``: ``LWP_SCAN_ROOT`` plus an isolated ``XDG_DATA_HOME``/``XDG_CACHE_HOME``.
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


def _file_rule_count(app: LinWallpapersApp) -> int:
    return int(
        app.services.writer.submit(
            lambda c: c.execute("SELECT count(*) FROM exclusion WHERE kind = 'file'").fetchone()[0]
        ).result()
    )


def main() -> int:
    scan_root = os.environ["LWP_SCAN_ROOT"]
    screenshot = sys.argv[1] if len(sys.argv) > 1 else None
    app = LinWallpapersApp("io.mensuramedia.LinWallpapers.Smoke", Gio.ApplicationFlags.NON_UNIQUE)
    result: dict[str, Any] = {}
    fired: set[str] = set()
    state: dict[str, Any] = {}

    def once(tag: str) -> bool:
        if tag in fired:
            return False
        fired.add(tag)
        return True

    def begin() -> bool:
        app.services.writer.submit(lambda c: set_setting(c, "scan.min_long_edge", 0)).result()
        app.sources_vm.add_root(scan_root, cb=lambda _snapshot: start_scan())
        return False

    def start_scan() -> None:
        app.scan_vm.add_observer(on_scan)
        app.scan_vm.start()

    def on_scan(scan_state: Any) -> None:
        if not scan_state.running and scan_state.result is not None and once("scan"):
            result["scan_result"] = scan_state.result
            GLib.idle_add(load_all)

    def load_all() -> bool:
        app.window.unmaximize()
        app.window.resize(Layout.dimensions.WINDOW_DEFAULT_WIDTH, Layout.dimensions.WINDOW_DEFAULT_HEIGHT)
        app.window.content_area.show_page("browse")
        app.browse_vm.refresh(cb=on_all)
        return False

    def on_all(grid: Any) -> None:
        if not once("all"):
            return
        result["all_total"] = grid.total
        state["card_id"] = grid.cards[0].id
        app.browse_vm.exclude_image(state["card_id"], cb=on_excluded)

    def on_excluded(outcome: Any) -> None:
        if not once("excluded"):
            return
        result["exclude_ok"] = bool(outcome.ok)
        result["rule_id"] = outcome.rule_id
        result["file_rules"] = _file_rule_count(app)
        app.browse_vm.refresh(cb=on_after_exclude)

    def on_after_exclude(grid: Any) -> None:
        if not once("after"):
            return
        result["after_exclude_total"] = grid.total
        GLib.timeout_add(400, shoot_then_undo)

    def shoot_then_undo() -> bool:
        if screenshot:
            gdk_window = app.window.get_window()
            width, height = gdk_window.get_width(), gdk_window.get_height()
            Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width, height).savev(screenshot, "png", [], [])
        app.browse_vm.undo_exclusion(result["rule_id"], cb=on_undone)
        return False

    def on_undone(_outcome: Any) -> None:
        if not once("undone"):
            return
        app.browse_vm.refresh(cb=on_after_undo)

    def on_after_undo(grid: Any) -> None:
        if not once("after_undo"):
            return
        result["after_undo_total"] = grid.total
        GLib.idle_add(drive_page_menu)

    def drive_page_menu() -> bool:
        # Exercise the real GTK path: open the card's context-menu popover (context_menu.py + the compat
        # gesture/popover), then run the page's exclude which arms the toast (toast.py).
        page = app.window.content_area.nav_manager.get_page_widget("browse")
        card = app.browse_vm.state.cards[0]
        popover = page._open_card_menu(page._grid, card, 12.0, 12.0)
        popover.popdown()  # dismiss the menu before the grid rebuilds, then exclude through the page
        page._exclude_image(card)
        result["menu_and_toast"] = True
        print("EXCL " + json.dumps(result))
        # Close well before the toast's 6 s auto-dismiss: its unrealize handler must drop the timeout.
        GLib.timeout_add(500, finish)
        return False

    def finish() -> bool:
        app.quit()
        return False

    app.connect("activate", lambda *_: GLib.timeout_add(250, begin))
    return int(app.run([]))


if __name__ == "__main__":
    sys.exit(main())
