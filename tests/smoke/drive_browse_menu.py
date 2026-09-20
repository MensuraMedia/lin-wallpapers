"""Drives a REAL right-click on a Browse *grid* card (inside the FlowBox) and asserts the menu opens.

Scans ``$LWP_SCAN_ROOT``, fills Browse, then synthesizes a real button-3 ``BUTTON_PRESS`` ``Gdk`` event
at the first card's own ``GdkWindow`` (the ``compat.click_target`` EventBox) and feeds it through
``Gtk.main_do_event`` — the real toplevel input path, NOT a direct call to the handler. Proves the fix
works even inside ``Gtk.FlowBox``/``FlowBoxChild``. Prints one ``BMENU {json}`` line.

GTK 3 introspection is used freely here: this is test code, not ported code.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

os.environ["GSETTINGS_BACKEND"] = "memory"

from src.catalogue.db import set_setting
from src.config.config_layout import Layout
from src.gtk_version import Gdk, Gio, GLib, Gtk
from src.main import LinWallpapersApp


def _button_event(target: Any) -> Any:
    gdk_window = target.get_window()
    alloc = target.get_allocation()
    win_x, win_y = alloc.width // 2, alloc.height // 2
    origin = gdk_window.get_origin()
    event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
    event.button = 3
    event.window = gdk_window
    event.x = float(win_x)
    event.y = float(win_y)
    event.x_root = float(origin.x + win_x)
    event.y_root = float(origin.y + win_y)
    event.state = 0
    event.time = 0
    seat = gdk_window.get_display().get_default_seat()
    pointer = seat.get_pointer() if seat is not None else None
    if pointer is not None:
        event.set_device(pointer)
    return event


def _drain() -> None:
    while Gtk.events_pending():
        Gtk.main_iteration()


def _first_card(app: LinWallpapersApp) -> Any:
    page = app.window.content_area.nav_manager.get_page_widget("browse")
    children = page._grid._flow.get_children()  # FlowBoxChild wrappers
    return children[0].get_child() if children else None


def main() -> int:
    scan_root = os.environ["LWP_SCAN_ROOT"]
    screenshot = sys.argv[1] if len(sys.argv) > 1 else None
    app = LinWallpapersApp("io.mensuramedia.LinWallpapers.Smoke", Gio.ApplicationFlags.NON_UNIQUE)
    facts: dict[str, Any] = {"menu_via": None, "menu_visible": False, "have_card": False}
    fired: set[str] = set()
    attempts = {"n": 0}

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
            GLib.idle_add(load_browse)

    def load_browse() -> bool:
        app.window.unmaximize()
        app.window.resize(Layout.dimensions.WINDOW_DEFAULT_WIDTH, Layout.dimensions.WINDOW_DEFAULT_HEIGHT)
        app.window.content_area.show_page("browse")
        app.browse_vm.refresh(cb=lambda _grid: GLib.timeout_add(50, wait_for_card))
        return False

    def wait_for_card() -> bool:
        attempts["n"] += 1
        card = _first_card(app)
        target = card.click_target if card is not None else None
        ready = target is not None and target.get_mapped() and target.get_allocation().width > 0
        if ready:
            do_right_click(card)
            return False
        if attempts["n"] > 120:
            emit_and_quit()
            return False
        return True

    def do_right_click(card: Any) -> None:
        facts["have_card"] = True
        facts["card_name"] = card.card.name
        # THE REAL PATH ONLY: a genuine button-3 event through the toplevel input machinery.
        Gtk.main_do_event(_button_event(card.click_target))
        _drain()
        menu = card.menu
        facts["menu_visible"] = menu is not None and bool(menu.get_visible())
        if facts["menu_visible"]:
            facts["menu_via"] = "main_do_event"
        GLib.timeout_add(300, shoot_then_quit)

    def shoot_then_quit() -> bool:
        if screenshot:
            gdk_window = app.window.get_window()
            width, height = gdk_window.get_width(), gdk_window.get_height()
            Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width, height).savev(screenshot, "png", [], [])
        emit_and_quit()
        return False

    def emit_and_quit() -> None:
        print("BMENU " + json.dumps(facts))
        app.quit()

    app.connect("activate", lambda *_: GLib.timeout_add(250, begin))
    return int(app.run([]))


if __name__ == "__main__":
    sys.exit(main())
