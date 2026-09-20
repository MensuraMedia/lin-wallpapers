"""Drives the real app: start, visit every route, measure the shell, close. Run by test_app_smoke.py
in a subprocess with G_DEBUG=fatal-criticals, so any GTK critical aborts it.

What it measures is printed as one ``FACTS {json}`` line; the assertions live in test_app_smoke.py.
Optional argv[1]: screenshot path; optional argv[2]: the route to screenshot (default: browse).

GTK 3 introspection (get_children, get_allocation, style contexts, ATK) is used freely here: the
smoke driver is test code, not ported code."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator
from typing import Any

# Never read or write the user's real settings from a test run: must be set before Gio starts.
os.environ["GSETTINGS_BACKEND"] = "memory"
# Nor the real catalogue/thumbnails: an isolated, empty XDG home keeps the shell smoke hermetic — the
# app opens a fresh catalogue and, with no roots, scans nothing (M1 acceptance #1).
if "XDG_DATA_HOME" not in os.environ:
    _tmp = tempfile.mkdtemp(prefix="lwp-smoke-")
    os.environ["XDG_DATA_HOME"] = _tmp + "/data"
    os.environ["XDG_CACHE_HOME"] = _tmp + "/cache"

from src.config.config_layout import Layout
from src.gtk_version import Gdk, Gio, GLib, Gtk
from src.main import LinWallpapersApp
from src.pages import ALL_PAGES, SIDEBAR_PAGES
from src.ui import compat
from src.ui.sidebar import NAV_ITEMS, LogoMark

TOKENS_MEASURED = ("accent", "bg-base", "bg-surface", "stroke")


def walk(widget: Any) -> Iterator[Any]:
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from walk(child)


def labels(widget: Any) -> list[Any]:
    return [child for child in walk(widget) if isinstance(child, Gtk.Label)]


def has_class(widget: Any, name: str) -> bool:
    return bool(widget.get_style_context().has_class(name))


def resolved_family(label: Any) -> str:
    """The family Pango actually loads for the label — not the CSS stack it was asked for."""
    context = label.get_pango_context()
    return str(context.load_font(context.get_font_description()).describe().get_family())


def rgb255(color: tuple[float, float, float, float]) -> list[int]:
    return [round(channel * 255) for channel in color[:3]]


def nav_facts(window: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for route, button in window.sidebar.nav_buttons.items():
        row = button.get_child()
        glyph = row.get_children()[0]
        facts[route] = {
            "label": labels(button)[0].get_text(),
            "height": button.get_allocation().height,
            "icon": [glyph.get_allocation().width, glyph.get_allocation().height],
        }
    return facts


def active_facts(window: Any) -> dict[str, Any]:
    """Which buttons carry ``active`` right now, and the glyph foreground of every button."""
    buttons = window.sidebar.nav_buttons
    return {
        "active": [route for route, button in buttons.items() if has_class(button, "active")],
        "glyph_color": {
            route: rgb255(compat.foreground_color(button.get_child().get_children()[0]))
            for route, button in buttons.items()
        },
    }


def grab(window: Any) -> Any:
    gdk_window = window.get_window()
    return Gdk.pixbuf_get_from_window(gdk_window, 0, 0, gdk_window.get_width(), gdk_window.get_height())


def hairline_facts(window: Any, pixbuf: Any) -> dict[str, Any] | None:
    """Pixels of the sidebar's right edge, in the empty stretch above the "this machine" panel."""
    if pixbuf is None:
        return None
    sidebar = window.sidebar
    left, _top = sidebar.translate_coordinates(window, 0, 0)
    _x, footer_top = sidebar.footer.translate_coordinates(window, 0, 0)
    y = footer_top - 12
    data, stride, channels = pixbuf.get_pixels(), pixbuf.get_rowstride(), pixbuf.get_n_channels()

    def pixel(x: int) -> list[int]:
        offset = y * stride + x * channels
        return list(data[offset : offset + 3])

    edge = left + sidebar.get_allocation().width - 1
    return {"edge": pixel(edge), "inside": pixel(edge - 3), "outside": pixel(edge + 3)}


def logo_facts(window: Any, pixbuf: Any) -> dict[str, Any]:
    """Where the logo block sits in the sidebar (x relative to the sidebar's allocation)."""
    sidebar = window.sidebar
    left, _top = sidebar.translate_coordinates(window, 0, 0)
    tile = next(widget for widget in walk(sidebar) if isinstance(widget, LogoMark))
    tile_x, tile_y = tile.translate_coordinates(window, 0, 0)
    size = tile.get_allocation()
    facts: dict[str, Any] = {
        "tile_centre": tile_x - left + size.width / 2,
        "tile_size": [size.width, size.height],
    }
    for key in ("logo-name", "logo-tagline"):
        label = next(widget for widget in labels(sidebar) if has_class(widget, key))
        # Layout offsets are in the coordinates of the label's GdkWindow — the toplevel's, for a label.
        layout_x, _layout_y = label.get_layout_offsets()
        _ink, logical = label.get_layout().get_pixel_extents()
        facts[key] = {"centre": layout_x + logical.x + logical.width / 2 - left, "xalign": label.get_xalign()}
    nav = next(iter(sidebar.nav_buttons.values()))
    facts["nav_label_xalign"] = labels(nav)[0].get_xalign()
    facts["footer_xalign"] = [label.get_xalign() for label in labels(sidebar.footer)]
    if pixbuf is not None:
        # The glyph is the only dark, blue-less ink on the tile (its corners blend into the blue surface).
        data, stride, channels = pixbuf.get_pixels(), pixbuf.get_rowstride(), pixbuf.get_n_channels()
        ink = [
            (x, y)
            for y in range(size.height)
            for x in range(size.width)
            if data[(tile_y + y) * stride + (tile_x + x) * channels] < 150
            and data[(tile_y + y) * stride + (tile_x + x) * channels + 2] < 25
        ]
        if ink:
            xs, ys = [x for x, _y in ink], [y for _x, y in ink]
            facts["glyph_margins"] = [min(xs), size.width - 1 - max(xs), min(ys), size.height - 1 - max(ys)]
    return facts


def shell_facts(window: Any) -> dict[str, Any]:
    all_labels = labels(window)
    pixbuf = grab(window)
    families = {family.get_name() for family in window.get_pango_context().get_font_map().list_families()}
    stack = window.content_area.stack
    return {
        "installed_families": sorted(families),
        "label_families": sorted({resolved_family(label) for label in all_labels}),
        "sidebar_width": window.sidebar.get_allocation().width,
        "nav": nav_facts(window),
        "footer": [label.get_text() for label in labels(window.sidebar.footer)],
        "page_titles": {
            page.route: [
                label.get_text()
                for label in labels(stack.get_child_by_name(page.route))
                if has_class(label, "page-title")
            ]
            for page in ALL_PAGES
        },
        "accessible": [[label.get_text(), label.get_accessible().get_name()] for label in all_labels],
        "tokens": {name: list(compat.lookup_color(window, name)) for name in TOKENS_MEASURED},
        "hairline": hairline_facts(window, pixbuf),
        "logo": logo_facts(window, pixbuf),
    }


def main() -> int:
    # Its own id + NON_UNIQUE: never attach to (or disturb) a running instance.
    app = LinWallpapersApp("io.mensuramedia.LinWallpapers.Smoke", Gio.ApplicationFlags.NON_UNIQUE)
    routes = [page.route for page in ALL_PAGES]
    visited: list[str] = []
    facts: dict[str, Any] = {"per_route": {}}
    screenshot = sys.argv[1] if len(sys.argv) > 1 else None
    shot_route = sys.argv[2] if len(sys.argv) > 2 else "browse"

    def step() -> bool:
        window = app.window
        assert window is not None
        nav = window.nav_manager
        if visited:
            # One tick after navigating, so the styles of the newly active button are settled.
            facts["per_route"][visited[-1]] = active_facts(window)
        if len(visited) < len(routes):
            route = routes[len(visited)]
            window.activate_action("navigate", GLib.Variant("s", route))
            assert nav.get_current_page() == route, route
            assert window.content_area.stack.get_visible_child_name() == route
            active = window.sidebar.active_button
            expected = window.sidebar.nav_buttons.get(route)
            assert active is expected, f"sidebar highlight wrong on {route}"
            visited.append(route)
            return True
        facts.update(shell_facts(window))
        if screenshot:
            # Mockup-sized, whatever size was remembered (GTK 3 only; the smoke driver is not ported code).
            window.unmaximize()
            window.resize(Layout.dimensions.WINDOW_DEFAULT_WIDTH, Layout.dimensions.WINDOW_DEFAULT_HEIGHT)
            window.activate_action("navigate", GLib.Variant("s", shot_route))
            GLib.timeout_add(400, shoot)
        else:
            app.activate_action("quit", None)  # the Ctrl+Q path, state saving included
        return False

    def shoot() -> bool:
        gdk_window = app.window.get_window()  # GTK 3 only; the smoke driver is not ported code
        width, height = gdk_window.get_width(), gdk_window.get_height()
        Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width, height).savev(screenshot, "png", [], [])
        app.quit()
        return False

    app.connect("activate", lambda *_: GLib.timeout_add(150, step))
    status = app.run([])

    assert [item[1] for item in NAV_ITEMS] == [page.route for page in SIDEBAR_PAGES]
    assert visited == routes, f"visited {visited}"
    print(f"smoke: visited {len(visited)} routes")
    print("FACTS " + json.dumps(facts))
    return int(status)


if __name__ == "__main__":
    sys.exit(main())
