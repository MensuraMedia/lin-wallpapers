"""The Wallpaper page — the curated library grid.

A tight ``Gtk.FlowBox`` of wallpaper tiles: the always-present built-in default
first, then everything the user has added (via the in-page buttons or the
file-manager "Add to LinWallpaper" context menu). Each tile can be applied to
every screen, sent to the Screens page, or removed. Nothing here touches the
filesystem directly — it all goes through ``state.collection``.
"""

from __future__ import annotations

from gi.repository import Gio, Gtk

from ... import imaging
from ..imgutil import texture_from_file
from .base import BasePage

_THUMB_W = 240
_THUMB_H = 150


class WallpaperPage(BasePage):
    route = "wallpaper"
    title = "Wallpaper"
    subtitle = "Your library — apply one to every screen, or send it to Screens to place per-surface."

    def build_content(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.set_vexpand(True)

        # Top bar: add controls + a count.
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        add_imgs = Gtk.Button(label="Add images…")
        add_imgs.add_css_class("lw-ghost")
        add_imgs.connect("clicked", lambda *_: self._on_add_images())
        add_dir = Gtk.Button(label="Add folder…")
        add_dir.add_css_class("lw-ghost")
        add_dir.connect("clicked", lambda *_: self._on_add_folder())
        bar.append(add_imgs)
        bar.append(add_dir)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)
        self._count = Gtk.Label(xalign=1.0)
        self._count.add_css_class("lw-sub")
        self._count.set_valign(Gtk.Align.CENTER)
        bar.append(self._count)
        outer.append(bar)

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_homogeneous(False)
        self.flow.set_hexpand(True)  # fill the width so tiles pack many-per-line
        self.flow.set_halign(Gtk.Align.START)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_max_children_per_line(8)
        self.flow.set_min_children_per_line(3)
        self.flow.set_column_spacing(12)
        self.flow.set_row_spacing(12)
        self.flow.add_css_class("lw-wp-grid")
        outer.append(self.flow)

        self._populate()
        return outer

    def refresh(self) -> None:
        # Re-read the library so context-menu additions appear on return here.
        if hasattr(self, "flow"):
            self._populate()

    # ---- grid -------------------------------------------------------------
    def _populate(self) -> None:
        child = self.flow.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.flow.remove(child)
            child = nxt

        items = self.state.collection.items()
        for item in items:
            self.flow.append(self._tile(item))

        extra = len(items) - 1  # exclude the built-in default from the "added" count
        self._count.set_text(f"{extra} added" if extra else "just the default")

    def _tile(self, item) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("lw-wp-card")
        # Fixed width + no expansion so cells stay tile-sized and pack many per
        # line; valign START keeps each card only as tall as its content.
        card.set_size_request(_THUMB_W, -1)
        card.set_hexpand(False)
        card.set_vexpand(False)
        card.set_halign(Gtk.Align.START)
        card.set_valign(Gtk.Align.START)

        overlay = Gtk.Overlay()
        pic = Gtk.Picture()
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(_THUMB_W, _THUMB_H)
        pic.add_css_class("lw-wp-thumb")
        missing = not item.exists
        if not missing:
            try:
                thumb = imaging.thumbnail(item.path, (_THUMB_W * 2, _THUMB_H * 2))
                pic.set_paintable(texture_from_file(thumb))
            except Exception:
                missing = True
        overlay.set_child(pic)

        if item.builtin:
            overlay.add_overlay(self._badge("DEFAULT"))
        if missing:
            overlay.add_overlay(self._badge("MISSING", warn=True))
        card.append(overlay)

        name = Gtk.Label(label=item.name, xalign=0.0)
        name.add_css_class("lw-wp-name")
        name.set_ellipsize(3)  # Pango.EllipsizeMode.END
        name.set_max_width_chars(20)
        card.append(name)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("lw-primary")
        apply_btn.set_size_request(_THUMB_W - 56, -1)  # fill most of the card, no hexpand
        apply_btn.set_sensitive(not missing)
        if missing:
            apply_btn.set_tooltip_text("file moved or deleted")
        apply_btn.connect("clicked", lambda *_a, p=item.path: self._apply(p))
        actions.append(apply_btn)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("view-more-symbolic")
        menu_btn.add_css_class("lw-ghost")
        menu_btn.set_popover(self._tile_menu(item))
        actions.append(menu_btn)
        card.append(actions)
        return card

    def _tile_menu(self, item) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(4)
        box.set_margin_end(4)

        use = Gtk.Button(label="Use in Screens")
        use.add_css_class("flat")
        use.set_sensitive(item.exists)
        use.connect("clicked", lambda *_a, p=item.path: (pop.popdown(), self._use_in_screens(p)))
        box.append(use)

        if item.removable:
            rm = Gtk.Button(label="Remove")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda *_a, p=item.path: (pop.popdown(), self._remove(p)))
            box.append(rm)
        pop.set_child(box)
        return pop

    def _badge(self, text: str, warn: bool = False) -> Gtk.Widget:
        lbl = Gtk.Label(label=text)
        lbl.add_css_class("lw-badge-good" if not warn else "lw-badge")
        lbl.set_halign(Gtk.Align.START)
        lbl.set_valign(Gtk.Align.START)
        lbl.set_margin_top(6)
        lbl.set_margin_start(6)
        return lbl

    # ---- actions ----------------------------------------------------------
    def _apply(self, path: str) -> None:
        self.win.apply("all", image=path, fit=self.state.fit)

    def _use_in_screens(self, path: str) -> None:
        self.state.clear_surface_images()
        self.state.set_image(path)  # notify() refreshes Screens cards
        self.win.navigate("screens")

    def _remove(self, path: str) -> None:
        if self.state.collection.remove(path):
            self._populate()

    # ---- adding -----------------------------------------------------------
    def _image_filters(self) -> Gio.ListStore:
        filt = Gtk.FileFilter()
        filt.set_name("Images")
        for mime in imaging.supported_mime_types():
            filt.add_mime_type(mime)
        for fmt in imaging.supported_formats():
            for ext in fmt["extensions"]:
                filt.add_suffix(ext)
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(filt)
        return store

    def _on_add_images(self) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Add images to your library")
        filters = self._image_filters()
        dialog.set_filters(filters)
        dialog.set_default_filter(filters.get_item(0))
        dialog.open_multiple(self.win, None, self._add_images_done)

    def _add_images_done(self, dlg, result) -> None:
        try:
            files = dlg.open_multiple_finish(result)
        except Exception:
            return
        paths = []
        for i in range(files.get_n_items()):
            gfile = files.get_item(i)
            p = gfile.get_path() if gfile else None
            if p:
                paths.append(p)
        self._add(paths)

    def _on_add_folder(self) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Add a folder of images")
        dialog.select_folder(self.win, None, self._add_folder_done)

    def _add_folder_done(self, dlg, result) -> None:
        try:
            folder = dlg.select_folder_finish(result)
        except Exception:
            return
        p = folder.get_path() if folder else None
        if p:
            self._add([p])

    def _add(self, paths: list[str]) -> None:
        if not paths:
            return
        res = self.state.collection.add_paths(paths)
        self._populate()
        msg = f"Added {res.added} to your library" if res.added else "Nothing new to add"
        if res.skipped:
            msg += f" ({res.skipped} skipped)"
        self.win.toast(msg)
