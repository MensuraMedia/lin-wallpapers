"""Wallpaper page — the main flow: open, preview, fit, target, apply."""

from __future__ import annotations

from gi.repository import Gdk, Gtk

from ... import imaging
from ..imgutil import pil_to_texture
from .base import BasePage


class WallpaperPage(BasePage):
    route = "wallpaper"
    title = "Wallpaper"
    subtitle = "Open an image, preview how it fits, and apply it to your desktop."

    def build_content(self) -> Gtk.Widget:
        cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        cols.set_vexpand(True)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        left.set_hexpand(True)

        # preview
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.picture.set_size_request(-1, 380)
        self.picture.add_css_class("lw-preview")
        self.picture.set_vexpand(True)
        # drag-and-drop onto the preview
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.picture.add_controller(drop)
        left.append(self.picture)

        # info chips
        self.chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._placeholder_chip()
        left.append(self.chips)

        # Fit segmented control
        fit_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        fit_lbl = Gtk.Label(label="FIT")
        fit_lbl.add_css_class("lw-label")
        fit_row.append(fit_lbl)
        fit_row.append(self._build_fit())
        left.append(fit_row)

        # target + open
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        tlbl = Gtk.Label(label="APPLY TO")
        tlbl.add_css_class("lw-label")
        bottom.append(tlbl)
        bottom.append(self._build_target())
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bottom.append(spacer)
        open_btn = Gtk.Button(label="+  Open image…")
        open_btn.add_css_class("lw-ghost")
        open_btn.connect("clicked", lambda *_: self.win.open_image_dialog())
        bottom.append(open_btn)
        left.append(bottom)

        # apply row
        apply_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        apply_row.set_margin_top(6)
        be_name = f"{self.state.backend.name} backend" if self.state.backend else "no backend"
        be_chip = Gtk.Label(label=be_name)
        be_chip.add_css_class("lw-chip")
        apply_row.append(be_chip)
        sp2 = Gtk.Box()
        sp2.set_hexpand(True)
        apply_row.append(sp2)
        self.apply_btn = Gtk.Button(label="Apply wallpaper")
        self.apply_btn.add_css_class("lw-primary")
        self.apply_btn.set_sensitive(False)
        self.apply_btn.connect("clicked", lambda *_: self.win.apply(self.state.target))
        apply_row.append(self.apply_btn)
        left.append(apply_row)

        cols.append(left)
        cols.append(self._build_screens_card())
        return cols

    # ---- sub-widgets ------------------------------------------------------
    def _build_fit(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("lw-seg")
        self._fit_btns: dict[str, Gtk.ToggleButton] = {}
        first = None
        for fit in imaging.FITS:
            btn = Gtk.ToggleButton(label=imaging.FIT_LABELS[fit])
            btn.set_has_frame(False)
            if first is None:
                first = btn
                btn.set_active(True)
            else:
                btn.set_group(first)
            btn.connect("toggled", self._on_fit, fit)
            self._fit_btns[fit] = btn
            box.append(btn)
        return box

    def _build_target(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("lw-seg")
        self._target_all = Gtk.ToggleButton(label="All screens")
        self._target_all.set_has_frame(False)
        self._target_all.set_active(True)
        self._target_one = Gtk.ToggleButton(label="This screen")
        self._target_one.set_has_frame(False)
        self._target_one.set_group(self._target_all)
        self._target_all.connect("toggled", self._on_target)
        self._target_one.connect("toggled", self._on_target)
        box.append(self._target_all)
        box.append(self._target_one)
        return box

    def _build_screens_card(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("lw-card")
        card.set_size_request(280, -1)
        card.set_valign(Gtk.Align.START)
        card.set_margin_start(0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_margin_top(16)
        inner.set_margin_bottom(16)
        inner.set_margin_start(16)
        inner.set_margin_end(16)
        title = Gtk.Label(label="Screens", xalign=0.0)
        title.add_css_class("lw-card-title")
        inner.append(title)
        mons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for mon in self.state.monitors:
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            tile.add_css_class("lw-preview")
            tile.set_size_request(90, 60)
            tile.set_valign(Gtk.Align.CENTER)
            tile.set_halign(Gtk.Align.CENTER)
            lbl = Gtk.Label(label=mon.name)
            lbl.add_css_class("lw-foot-body")
            lbl.set_vexpand(True)
            lbl.set_valign(Gtk.Align.END)
            tile.append(lbl)
            mons.append(tile)
        inner.append(mons)
        hint = Gtk.Label(xalign=0.0)
        hint.add_css_class("lw-sub")
        hint.set_wrap(True)
        hint.set_markup(
            "Applying to <b>all screens</b>. Switch to “This screen” to set one monitor."
        )
        inner.append(hint)
        card.append(inner)
        return card

    def _placeholder_chip(self) -> None:
        child = self.chips.get_first_child()
        while child:
            self.chips.remove(child)
            child = self.chips.get_first_child()
        lbl = Gtk.Label(label="No image chosen")
        lbl.add_css_class("lw-chip")
        self.chips.append(lbl)

    # ---- events -----------------------------------------------------------
    def _on_fit(self, btn, fit):
        if btn.get_active():
            self.state.set_fit(fit)

    def _on_target(self, *_):
        target = "all"
        if self._target_one.get_active():
            target = self.state.monitors[0].name if self.state.monitors else "all"
        self.state.set_target(target)

    def _on_drop(self, _drop, value, _x, _y):
        try:
            files = value.get_files()
            if files:
                self.state.set_image(files[0].get_path())
                return True
        except Exception:
            pass
        return False

    # ---- refresh ----------------------------------------------------------
    def refresh(self) -> None:
        self.apply_btn.set_sensitive(self.state.image_path is not None)
        # sync fit buttons
        for fit, btn in self._fit_btns.items():
            if fit == self.state.fit and not btn.get_active():
                btn.set_active(True)
        if not self.state.image_path:
            self._placeholder_chip()
            self.picture.set_paintable(None)
            return
        # preview via the shared transform (matches apply)
        mon = self.state.monitors[0] if self.state.monitors else None
        size = (mon.px_width, mon.px_height) if mon else (1920, 1080)
        # scale preview size down for speed, same aspect/fit
        pw = 960
        ph = max(1, round(pw * size[1] / size[0]))
        try:
            img = imaging.transform(self.state.image_path, (pw, ph), self.state.fit)
            self.picture.set_paintable(pil_to_texture(img))
        except Exception:
            self.picture.set_paintable(None)
        self._fill_chips()

    def _fill_chips(self) -> None:
        child = self.chips.get_first_child()
        while child:
            self.chips.remove(child)
            child = self.chips.get_first_child()
        try:
            meta = imaging.probe(self.state.image_path)
        except Exception:
            return
        for text in (meta["name"], f"{meta['width']} × {meta['height']}", meta["format"]):
            lbl = Gtk.Label(label=text)
            lbl.add_css_class("lw-chip")
            self.chips.append(lbl)
        fits = Gtk.Label(label="✓ fits your screen")
        fits.add_css_class("lw-chip")
        fits.add_css_class("good")
        self.chips.append(fits)
