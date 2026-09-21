"""The wallpaper picker — the library shown when choosing *Image* on Screens.

A small modal that lists the collection as thumbnails; picking one calls the
same ``on_chosen(path)`` callback the Screens Image buttons already use, so
nothing downstream changes. **Browse files…** falls through to the normal file
dialog, preserving the file-anywhere workflow.
"""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from .. import imaging
from .imgutil import texture_from_file

_THUMB_W = 220
_THUMB_H = 138


class WallpaperPicker(Adw.Window):
    def __init__(self, win, state, on_chosen: Callable[[str], None]) -> None:
        super().__init__()
        self._win = win
        self._state = state
        self._on_chosen = on_chosen
        self.set_transient_for(win)
        self.set_modal(True)
        self.set_title("Choose a wallpaper")
        self.set_default_size(760, 560)

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        view.add_top_bar(header)

        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(False)
        flow.set_hexpand(True)
        flow.set_halign(Gtk.Align.START)
        flow.set_valign(Gtk.Align.START)
        flow.set_max_children_per_line(6)
        flow.set_min_children_per_line(3)
        flow.set_column_spacing(12)
        flow.set_row_spacing(12)
        flow.set_margin_top(12)
        flow.set_margin_bottom(12)
        flow.set_margin_start(12)
        flow.set_margin_end(12)
        state.collection.reload()  # pick up any external additions
        for item in state.collection.items():
            flow.append(self._tile(item))

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(flow)
        view.set_content(scroller)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bottom.set_margin_top(8)
        bottom.set_margin_bottom(8)
        bottom.set_margin_start(12)
        bottom.set_margin_end(12)
        browse = Gtk.Button(label="Browse files…")
        browse.add_css_class("lw-ghost")
        browse.connect("clicked", lambda *_: self._browse())
        bottom.append(browse)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bottom.append(spacer)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        bottom.append(cancel)
        view.add_bottom_bar(bottom)

        self.set_content(view)

    def _tile(self, item) -> Gtk.Widget:
        btn = Gtk.Button()
        btn.add_css_class("flat")
        btn.add_css_class("lw-wp-pick")
        btn.set_size_request(_THUMB_W, -1)
        btn.set_hexpand(False)
        btn.set_vexpand(False)
        btn.set_halign(Gtk.Align.START)
        btn.set_valign(Gtk.Align.START)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pic = Gtk.Picture()
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(_THUMB_W, _THUMB_H)
        pic.add_css_class("lw-wp-thumb")
        enabled = item.exists
        if enabled:
            try:
                thumb = imaging.thumbnail(item.path, (_THUMB_W * 2, _THUMB_H * 2))
                pic.set_paintable(texture_from_file(thumb))
            except Exception:
                enabled = False
        box.append(pic)
        name = Gtk.Label(label=item.name, xalign=0.5)
        name.add_css_class("lw-wp-name")
        name.set_ellipsize(3)
        name.set_max_width_chars(20)
        box.append(name)
        btn.set_child(box)
        btn.set_sensitive(enabled)
        btn.connect("clicked", lambda *_a, p=item.path: self._pick(p))
        return btn

    def _pick(self, path: str) -> None:
        self.close()
        self._on_chosen(path)

    def _browse(self) -> None:
        self.close()
        self._win.open_image_dialog(on_chosen=self._on_chosen)
