"""Drives a REAL right-click on the Test page's plain card, then asserts the context menu opens.

``LWP_TEST_IMAGE_DIR`` (set by the test) points ``TestVM`` at a seeded directory holding one image, so
the card loads deterministically without a scan. The driver navigates to the Test page, waits for the
card, then synthesizes a real secondary-button (button 3) ``BUTTON_PRESS`` ``Gdk`` event at the card's
coordinates and feeds it through the real event machinery — NOT by calling the card's handler. It first
tries ``Gtk.main_do_event`` (the toplevel input path); GTK 3 routes button events by GdkWindow and the
card is a windowless ``Gtk.Box``, so if that does not reach the card's gesture it then dispatches the same
event through ``Gtk.Widget.event(card, ...)`` — the widget/gesture-controller's real event handling (still
an event, not the handler). Either way the popover the gesture opens is asserted visible.

Prints one ``MENU {json}`` line; assertions live in ``test_test_page_menu.py``.
GTK 3 introspection is used freely here: this is test code, not ported code.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

os.environ["GSETTINGS_BACKEND"] = "memory"

from src.config.config_layout import Layout
from src.gtk_version import Gdk, Gio, GLib, Gtk
from src.main import LinWallpapersApp


def _button_event(target: Any) -> Any:
    """A real ``BUTTON_PRESS`` (button 3) event at the centre of ``target``'s own GdkWindow.

    ``target`` must be a widget that owns a ``GdkWindow`` (a ``compat.click_target``); a real pointer
    click lands on that window, so the synthetic event carries it as ``event.window`` — exactly what
    ``Gtk.main_do_event`` routes on.
    """
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


def _menu_open(card: Any) -> bool:
    return card.menu is not None and bool(card.menu.get_visible())


def main() -> int:
    screenshot = sys.argv[1] if len(sys.argv) > 1 else None
    app = LinWallpapersApp("io.mensuramedia.LinWallpapers.Smoke", Gio.ApplicationFlags.NON_UNIQUE)
    facts: dict[str, Any] = {"menu_via": None, "menu_visible": False, "have_card": False}
    attempts = {"n": 0}

    def page() -> Any:
        return app.window.content_area.nav_manager.get_page_widget("test")

    def begin() -> bool:
        app.window.unmaximize()
        app.window.resize(Layout.dimensions.WINDOW_DEFAULT_WIDTH, Layout.dimensions.WINDOW_DEFAULT_HEIGHT)
        app.window.content_area.show_page("test")
        GLib.timeout_add(50, wait_for_card)
        return False

    def wait_for_card() -> bool:
        attempts["n"] += 1
        card = page().card
        target = card.click_target if card is not None else None
        ready = target is not None and target.get_mapped() and target.get_allocation().width > 0
        if ready:
            do_right_click(card)
            return False
        if attempts["n"] > 120:  # ~6 s
            facts["loaded"] = page().loaded
            emit_and_quit()
            return False
        return True

    def do_right_click(card: Any) -> None:
        facts["have_card"] = True
        facts["image_name"] = card._image.name  # the DTO the VM delivered

        # THE REAL PATH ONLY: a genuine button-3 event through the toplevel input machinery. No direct
        # dispatch to the widget — if this does not open the menu, the wiring is not proven.
        Gtk.main_do_event(_button_event(card.click_target))
        _drain()
        if _menu_open(card):
            facts["menu_via"] = "main_do_event"

        facts["menu_visible"] = _menu_open(card)
        facts["loaded"] = page().loaded
        GLib.timeout_add(300, shoot_then_quit)

    def shoot_then_quit() -> bool:
        if screenshot:
            gdk_window = app.window.get_window()
            width, height = gdk_window.get_width(), gdk_window.get_height()
            Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width, height).savev(screenshot, "png", [], [])
        emit_and_quit()
        return False

    def emit_and_quit() -> None:
        print("MENU " + json.dumps(facts))
        app.quit()

    app.connect("activate", lambda *_: GLib.timeout_add(250, begin))
    return int(app.run([]))


if __name__ == "__main__":
    sys.exit(main())
