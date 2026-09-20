"""Screens page — a card per Gdk.Monitor with a per-monitor Choose image."""

from __future__ import annotations

from gi.repository import Gtk

from ... import imaging
from ..imgutil import pil_to_texture
from .base import BasePage


class ScreensPage(BasePage):
    route = "screens"
    title = "Screens"
    subtitle = "Each monitor and the image it shows. Pick a screen to give it its own wallpaper."

    def build_content(self) -> Gtk.Widget:
        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_max_children_per_line(2)
        self.flow.set_min_children_per_line(1)
        self.flow.set_column_spacing(18)
        self.flow.set_row_spacing(18)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._rebuild()
        return self.flow

    def _rebuild(self) -> None:
        child = self.flow.get_first_child()
        while child:
            self.flow.remove(child)
            child = self.flow.get_first_child()
        for mon in self.state.monitors:
            self.flow.append(self._card(mon))

    def _card(self, mon) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class("lw-screen-card")
        card.set_size_request(330, -1)
        if mon.name == self.state.target:
            card.add_css_class("target")

        pic = Gtk.Picture()
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(330, 170)
        img_path = self.state.per_screen.get(mon.name) or self.state.image_path
        if img_path:
            try:
                thumb = imaging.transform(img_path, (330, 170), imaging.FIT_FILL)
                pic.set_paintable(pil_to_texture(thumb))
            except Exception:
                pass
        card.append(pic)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.set_margin_top(12)
        body.set_margin_bottom(14)
        body.set_margin_start(14)
        body.set_margin_end(14)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = Gtk.Label(label=mon.name, xalign=0.0)
        name.add_css_class("lw-card-title")
        head.append(name)
        if mon.primary:
            badge = Gtk.Label(label="PRIMARY")
            badge.add_css_class("lw-badge")
            badge.set_valign(Gtk.Align.CENTER)
            head.append(badge)
        sp = Gtk.Box()
        sp.set_hexpand(True)
        head.append(sp)
        if mon.name == self.state.target:
            tgt = Gtk.Label(label="● target")
            tgt.add_css_class("lw-foot-title")
            head.append(tgt)
        body.append(head)

        meta = Gtk.Label(label=f"{mon.px_width} × {mon.px_height} · scale {mon.scale}×", xalign=0.0)
        meta.add_css_class("lw-sub")
        body.append(meta)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        shown = img_path.split("/")[-1] if img_path else "—"
        showing = Gtk.Label(xalign=0.0)
        showing.add_css_class("dim")
        showing.set_markup(f"Showing <b>{GLib_escape(shown)}</b>")
        showing.set_hexpand(True)
        row.append(showing)
        choose = Gtk.Button(label="Choose image…")
        choose.add_css_class("lw-ghost")
        choose.connect("clicked", self._on_choose, mon.name)
        row.append(choose)
        body.append(row)

        card.append(body)
        return card

    def _on_choose(self, _btn, connector: str) -> None:
        self.state.set_target(connector)

        def done(path: str) -> None:
            self.state.per_screen[connector] = path
            self.state.set_image(path)

        self.win.open_image_dialog(done)

    def refresh(self) -> None:
        self._rebuild()


def GLib_escape(text: str) -> str:
    from gi.repository import GLib

    return GLib.markup_escape_text(text)
