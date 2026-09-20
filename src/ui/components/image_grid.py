"""The Browse results grid: a ``Gtk.FlowBox`` in a ``Gtk.ScrolledWindow`` (M1 §2.9, D16).

A 20,000-child flow box cannot hit 60 fps, so the grid renders only the sliding window of cards the
``BrowseVM`` hands it (≤ 600) and asks for the next page when the user scrolls near the bottom. The
component is fed DTOs and a ``load_thumb`` callback; it never touches the catalogue or the filesystem.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat
from src.ui.components.image_card import ImageCard

MAX_CARDS = 600  # D16: the flow box never holds more than this many children
_NEAR_BOTTOM_PX = 400  # ask for more this far from the end


class ImageGrid(Gtk.Box):  # type: ignore[misc]
    """A scrolling, wrapping grid of :class:`ImageCard` widgets over the view model's paged window."""

    def __init__(
        self,
        load_thumb: Callable[[int, Callable[[Any], None]], Any],
        on_activate: Callable[[int], None] | None = None,
        on_need_more: Callable[[], None] | None = None,
        on_context_menu: Callable[[Any, Any, float, float], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._load_thumb = load_thumb
        self._on_activate = on_activate
        self._on_need_more = on_need_more
        self._on_context_menu = on_context_menu
        self._empty: Any = None
        compat.add_class(self, "image-grid")

        self._flow = Gtk.FlowBox()
        self._flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flow.set_homogeneous(True)
        self._flow.set_row_spacing(Layout.spacing.PAGE_GAP)
        self._flow.set_column_spacing(Layout.spacing.PAGE_GAP)
        self._flow.set_max_children_per_line(8)
        self._flow.set_valign(Gtk.Align.START)

        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroller.set_vexpand(True)
        self._scroller.set_min_content_height(360)
        compat.set_child(self._scroller, self._flow)
        self._scroller.get_vadjustment().connect("value-changed", self._on_scroll)
        compat.append(self, self._scroller, expand=True)

    def set_cards(self, cards: Sequence[Any]) -> None:
        """Replace the visible window with ``cards`` (capped at :data:`MAX_CARDS`)."""
        self._remove_empty()
        compat.clear_children(self._flow)
        for card in cards[:MAX_CARDS]:
            self._flow.insert(
                ImageCard(card, self._load_thumb, self._on_activate, self._on_context_menu), -1
            )
        compat.show(self._flow)

    def show_empty(self, widget: Any) -> None:
        """Show an empty-state ``widget`` instead of the grid (no results, offline drive, …)."""
        compat.clear_children(self._flow)
        self._remove_empty()
        self._empty = widget
        compat.append(self, widget)
        compat.show(widget)

    def _remove_empty(self) -> None:
        if self._empty is not None:
            self.remove(self._empty)
            self._empty = None

    def _on_scroll(self, adjustment: Any) -> None:
        if self._on_need_more is None:
            return
        remaining = adjustment.get_upper() - (adjustment.get_value() + adjustment.get_page_size())
        if remaining <= _NEAR_BOTTOM_PX:
            self._on_need_more()
