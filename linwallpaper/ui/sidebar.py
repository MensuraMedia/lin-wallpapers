"""The fixed 200 px sidebar: brand tile, nav rows, THIS MACHINE footer."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gtk

# starter convention: (label, route, icon-name)
NAV_ITEMS = (
    ("Wallpaper", "wallpaper", "image-x-generic-symbolic"),
    ("Screens", "screens", "video-display-symbolic"),
    ("Settings", "settings", "emblem-system-symbolic"),
)


class Sidebar(Gtk.Box):
    def __init__(self, state, on_navigate: Callable[[str], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(200, -1)
        self.set_hexpand(False)
        self.add_css_class("lw-sidebar")
        self._on_navigate = on_navigate
        self._buttons: dict[str, Gtk.ToggleButton] = {}

        self.append(self._build_brand())

        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        nav.add_css_class("lw-nav")
        nav.set_margin_top(8)
        first: Gtk.ToggleButton | None = None
        for label, route, icon in NAV_ITEMS:
            btn = Gtk.ToggleButton()
            btn.set_has_frame(False)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.append(Gtk.Image.new_from_icon_name(icon))
            lbl = Gtk.Label(label=label, xalign=0.0)
            row.append(lbl)
            btn.set_child(row)
            if first is None:
                first = btn
            else:
                btn.set_group(first)
            btn.connect("toggled", self._on_toggled, route)
            self._buttons[route] = btn
            nav.append(btn)
        self.append(nav)

        self.append(self._build_footer(state))

    def _build_brand(self) -> Gtk.Widget:
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        brand.add_css_class("lw-brand")
        logo = Gtk.Image.new_from_icon_name("preferences-desktop-wallpaper-symbolic")
        logo.set_pixel_size(20)
        logo.add_css_class("lw-logo")
        logo.set_size_request(34, 34)
        brand.append(logo)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name = Gtk.Label(label="LinWallpaper", xalign=0.0)
        name.add_css_class("lw-brand-name")
        sub = Gtk.Label(label="GTK 4", xalign=0.0)
        sub.add_css_class("lw-brand-sub")
        names.append(name)
        names.append(sub)
        brand.append(names)
        return brand

    def _build_footer(self, state) -> Gtk.Widget:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.set_vexpand(True)
        wrap.set_valign(Gtk.Align.END)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("lw-foot")
        title = Gtk.Label(label="THIS MACHINE", xalign=0.0)
        title.add_css_class("lw-foot-title")
        card.append(title)
        for mon in state.monitors:
            row = Gtk.Label(
                label=f"{mon.name} · {mon.px_width}×{mon.px_height}", xalign=0.0
            )
            row.add_css_class("lw-foot-body")
            card.append(row)
        desk = Gtk.Label(label=state.desktop, xalign=0.0)
        desk.add_css_class("lw-foot-body")
        card.append(desk)
        wrap.append(card)
        return wrap

    def _on_toggled(self, btn: Gtk.ToggleButton, route: str) -> None:
        if btn.get_active():
            btn.add_css_class("selected")
            self._on_navigate(route)
        else:
            btn.remove_css_class("selected")

    def select(self, route: str) -> None:
        btn = self._buttons.get(route)
        if btn and not btn.get_active():
            btn.set_active(True)
