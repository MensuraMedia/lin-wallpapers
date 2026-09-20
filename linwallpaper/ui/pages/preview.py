"""Preview page — a larger fitted preview inside a simple mock desktop frame."""

from __future__ import annotations

from gi.repository import Gtk

from ... import imaging
from ..imgutil import pil_to_texture
from .base import BasePage


class PreviewPage(BasePage):
    route = "preview"
    title = "Preview"
    subtitle = "How the chosen image looks as your desktop, before you commit."

    def build_content(self) -> Gtk.Widget:
        frame = Gtk.Overlay()
        frame.add_css_class("lw-preview")
        frame.set_vexpand(True)

        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.picture.set_vexpand(True)
        self.picture.set_hexpand(True)
        frame.set_child(self.picture)

        # mock desktop icons (top-left)
        icons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        icons.set_halign(Gtk.Align.START)
        icons.set_valign(Gtk.Align.START)
        icons.set_margin_top(20)
        icons.set_margin_start(20)
        for _ in range(3):
            dot = Gtk.Box()
            dot.set_size_request(38, 38)
            dot.add_css_class("lw-chip")
            icons.append(dot)
        frame.add_overlay(icons)

        # mock panel + clock (bottom)
        panel = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        panel.set_valign(Gtk.Align.END)
        panel.add_css_class("lw-sidebar")
        panel.set_size_request(-1, 34)
        sp = Gtk.Box()
        sp.set_hexpand(True)
        panel.append(sp)
        self.clock = Gtk.Label(label="")
        self.clock.add_css_class("lw-foot-body")
        self.clock.set_margin_end(16)
        panel.append(self.clock)
        frame.add_overlay(panel)

        return frame

    def refresh(self) -> None:
        from datetime import datetime

        self.clock.set_text(datetime.now().strftime("%H:%M"))
        if not self.state.image_path:
            self.picture.set_paintable(None)
            return
        mon = self.state.monitors[0] if self.state.monitors else None
        aspect = (mon.px_width / mon.px_height) if mon else (16 / 9)
        pw = 1100
        ph = max(1, round(pw / aspect))
        try:
            img = imaging.transform(self.state.image_path, (pw, ph), self.state.fit)
            self.picture.set_paintable(pil_to_texture(img))
        except Exception:
            self.picture.set_paintable(None)
