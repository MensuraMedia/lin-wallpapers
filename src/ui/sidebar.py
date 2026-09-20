"""Sidebar (starter-template convention): logo block, route buttons, "this machine" footer slot."""

from __future__ import annotations

import math
from typing import Any, ClassVar

import cairo

from src import APP_NAME
from src.config.config_layout import Layout
from src.gtk_version import GObject, Gtk
from src.ui import compat
from src.ui.components.nav_glyph import GLYPHS, GRID, NavGlyph, rounded_rect

# (label, route, symbolic icon) — the template's nav_items tuples, in Ctrl+1…8 order. The symbolic icon
# is the fallback for a route without a drawn glyph (components/nav_glyph.py).
NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("Browse", "browse", "view-grid-symbolic"),
    ("Image", "image", "image-x-generic-symbolic"),
    ("Screens", "screens", "video-display-symbolic"),
    ("Preview", "preview", "view-reveal-symbolic"),
    ("Sources", "sources", "folder-symbolic"),
    ("Collections", "collections", "view-list-symbolic"),
    ("History", "history", "document-open-recent-symbolic"),
    ("Settings", "settings", "emblem-system-symbolic"),
)

TAGLINE = "EVERY SCREEN"

# The "this machine" panel before M3: it says when detection arrives and states no fact about the machine.
FOOTER_TITLE = "THIS MACHINE"
FOOTER_NOTE = "Detected in M3"


class LogoMark(compat.CanvasArea):
    """The yellow rounded tile with the wallpaper-on-a-screen glyph, drawn from tokens (no image asset)."""

    def __init__(self) -> None:
        size = Layout.dimensions.LOGO_SIZE
        super().__init__(size, size)
        self.set_halign(Gtk.Align.CENTER)

    def on_draw(self, cr: Any, width: int, height: int) -> None:
        size = min(width, height)
        rounded_rect(cr, 0, 0, size, size, Layout.dimensions.LOGO_RADIUS)
        gradient = cairo.LinearGradient(0, 0, size, size)
        gradient.add_color_stop_rgba(0, *compat.lookup_color(self, "accent"))
        gradient.add_color_stop_rgba(1, *compat.lookup_color(self, "accent-2"))
        cr.set_source(gradient)
        cr.fill()

        # A screen showing a landscape, on a stand — the mockup's 24-unit glyph.
        glyph = Layout.dimensions.LOGO_GLYPH_SIZE
        cr.translate((size - glyph) / 2, (size - glyph) / 2)
        cr.scale(glyph / GRID, glyph / GRID)
        cr.set_source_rgba(*compat.lookup_color(self, "on-accent"))
        cr.set_line_width(1.8)
        cr.set_line_cap(cairo.LineCap.ROUND)
        cr.set_line_join(cairo.LineJoin.ROUND)
        rounded_rect(cr, 3, 4, 18, 13, 2)
        cr.move_to(3, 14)
        for x, y in ((7.5, 10), (11, 13), (14.5, 9), (21, 14)):
            cr.line_to(x, y)
        cr.new_sub_path()
        cr.arc(9, 8.5, 1.3, 0, 2 * math.pi)
        cr.move_to(8, 20)
        cr.line_to(16, 20)
        cr.stroke()


class Sidebar(Gtk.Box):  # type: ignore[misc]
    """Fixed 150 px sidebar. Emits ``page-changed`` with the route key."""

    __gsignals__: ClassVar[dict[str, Any]] = {"page-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, navigation_manager: Any) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.SIDEBAR_GAP)
        self.nav_manager = navigation_manager
        self.set_size_request(Layout.dimensions.SIDEBAR_WIDTH, -1)
        compat.add_class(self, "sidebar")

        self.nav_buttons: dict[str, Any] = {}
        self.active_button: Any = None

        self.build_logo_area()
        self.build_navigation()
        self.build_footer()
        self.nav_manager.on_navigate(self.sync_active)

    def build_logo_area(self) -> None:
        """Tile, name and tagline as one centred unit — a deliberate deviation from the mockup's left edge."""
        logo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.LOGO_GAP)
        # The sidebar pads 12 px left and 13 px right (the hairline's pixel): one pixel of start margin
        # puts the block's centre on the sidebar's own centre, x = 75, instead of 74.
        logo_box.set_margin_start(Layout.spacing.HAIR)
        compat.append(logo_box, LogoMark())
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.HAIR)

        name = Gtk.Label(label=APP_NAME)
        name.set_xalign(0.5)
        compat.add_class(name, "logo-name")
        compat.append(names, name)

        tagline = Gtk.Label()
        compat.set_tracked_text(tagline, TAGLINE)
        tagline.set_xalign(0.5)
        compat.add_class(tagline, "logo-tagline")
        compat.append(names, tagline)
        compat.append(logo_box, names)
        compat.append(self, logo_box)

    def build_navigation(self) -> None:
        nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.NAV_GAP)
        for label, route, icon_name in NAV_ITEMS:
            button = self.create_nav_button(label, route, icon_name)
            self.nav_buttons[route] = button
            compat.append(nav_box, button)
        compat.append(self, nav_box)

    def build_footer(self) -> None:
        """The "this machine" panel. Capability probes arrive in M3; until then it says so (no fake data)."""
        compat.append(self, Gtk.Box(), expand=True)
        self.footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.PANEL_GAP)
        compat.add_class(self.footer, "machine-panel")
        for text, css_class in ((FOOTER_TITLE, "eyebrow"), (FOOTER_NOTE, "machine-note")):
            line = Gtk.Label()
            if css_class == "eyebrow":
                compat.set_tracked_text(line, text)
            else:
                line.set_text(text)
            line.set_xalign(0)
            compat.add_class(line, css_class)
            compat.append(self.footer, line)
        compat.append(self, self.footer)

    def create_nav_button(self, label: str, route: str, icon_name: str) -> Any:
        button = Gtk.Button()
        compat.add_class(button, "nav-button", "flat")
        button.set_size_request(-1, Layout.dimensions.NAV_BUTTON_HEIGHT)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.SMALL)
        size = Layout.dimensions.NAV_ICON_SIZE
        compat.append(row, NavGlyph(route, size) if route in GLYPHS else compat.icon(icon_name, size))
        text = Gtk.Label(label=label)
        text.set_xalign(0)
        compat.append(row, text)
        compat.set_child(button, row)
        button.connect("clicked", self.on_nav_clicked, route)
        return button

    def sync_active(self, route: str) -> None:
        """Follow the navigation manager, so shortcuts and in-page links highlight too."""
        if self.active_button is not None:
            compat.remove_class(self.active_button, "active")
        self.active_button = self.nav_buttons.get(route)
        if self.active_button is not None:
            compat.add_class(self.active_button, "active")

    def on_nav_clicked(self, _button: Any, route: str) -> None:
        self.emit("page-changed", route)
