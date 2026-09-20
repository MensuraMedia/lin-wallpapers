"""One image card in the Browse grid (M1 §2.9, D16).

The card is fed a frozen ``ImageCard`` DTO from ``BrowseVM`` and a ``load_thumb(id, cb)`` callback;
it never touches the filesystem and never sees a path — the thumbnail arrives as **bytes** (or a
placeholder DTO). The score-ring slot is reserved but empty until M2.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk, Pango
from src.ui import compat

THUMB_WIDTH = 208
THUMB_HEIGHT = 132

# reason -> the short line a placeholder tile shows when there are no thumbnail bytes.
_PLACEHOLDER_TEXT = {
    "none": "No preview",
    "failed": "Preview failed",
    "missing": "Drive offline",
}


class ImageCard(Gtk.Box):  # type: ignore[misc]
    """A thumbnail, filename and resolution chip for one catalogued image."""

    def __init__(
        self,
        card: Any,
        load_thumb: Callable[[int, Callable[[Any], None]], Any],
        on_activate: Callable[[int], None] | None = None,
        on_context_menu: Callable[[Any, Any, float, float], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.XSMALL)
        self.card = card
        self._on_activate = on_activate
        self._on_context_menu = on_context_menu
        compat.add_class(self, "image-card")
        if card.missing or card.excluded or card.unusable:
            compat.add_class(self, "dimmed")

        self._thumb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._thumb.set_size_request(THUMB_WIDTH, THUMB_HEIGHT)
        self._thumb.set_halign(Gtk.Align.CENTER)
        self._thumb.set_valign(Gtk.Align.CENTER)
        compat.add_class(self._thumb, "thumb")
        # The score ring (M2) will live in this reserved slot; empty until then.
        compat.append(self, self._thumb)

        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.XSMALL)
        name = Gtk.Label(label=card.name)
        name.set_xalign(0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_hexpand(True)
        compat.add_class(name, "card-name")
        compat.append(meta, name, expand=True)
        if card.width and card.height:
            chip = Gtk.Label(label=f"{card.width}×{card.height}")
            compat.add_class(chip, "res-chip", "tabular")
            compat.append(meta, chip)
        compat.append(self, meta)

        if on_activate is not None:
            compat.click_gesture(self, self._clicked)
        if on_context_menu is not None:
            compat.secondary_click_gesture(self, self._context_menu)

        self._show_placeholder("none")
        load_thumb(card.id, self._on_thumb)

    def _clicked(self, _n_press: int, _x: float, _y: float) -> None:
        if self._on_activate is not None:
            self._on_activate(self.card.id)

    def _context_menu(self, _n_press: int, x: float, y: float) -> None:
        if self._on_context_menu is not None:
            self._on_context_menu(self, self.card, x, y)

    def _on_thumb(self, result: Any) -> None:
        if isinstance(result, bytes | bytearray):
            image = compat.image_from_bytes(bytes(result), THUMB_WIDTH, THUMB_HEIGHT)
            if image is not None:
                self._set_thumb_child(image)
                return
            self._show_placeholder("failed")
            return
        self._show_placeholder(getattr(result, "reason", "none"))

    def _set_thumb_child(self, child: Any) -> None:
        compat.clear_children(self._thumb)
        compat.append(self._thumb, child)
        compat.show(child)

    def _show_placeholder(self, reason: str) -> None:
        compat.clear_children(self._thumb)
        label = Gtk.Label(label=_PLACEHOLDER_TEXT.get(reason, _PLACEHOLDER_TEXT["none"]))
        compat.add_class(label, "thumb-empty")
        compat.append(self._thumb, label)
        compat.show(label)
