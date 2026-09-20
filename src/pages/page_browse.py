"""Browse page (M1 §2.9, acceptance #2): the results grid, a segment switch and the filter bar.

Everything is driven by the injected ``BrowseVM``: the segment switch flips ``All / Ideal for this
desktop / Near misses``, the filter bar narrows the query, and the grid renders the paged sliding
window (thumbnails arrive as bytes). No catalogue type is imported — only the view model and the enum
classes handed in through the page context.
"""

from __future__ import annotations

from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat
from src.ui.components.filter_bar import FilterBar
from src.ui.components.image_grid import ImageGrid

from .page_base import BasePage


class BrowsePage(BasePage):
    route = "browse"
    title = "Browse"
    wants_context = True

    def __init__(self, context: Any = None) -> None:
        self.context = context
        super().__init__()

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("Every image on this machine that could be a wallpaper.")

        self._vm: Any = getattr(self.context, "browse_vm", None)
        self._segment_enum: Any = getattr(self.context, "segment", None)
        if self._vm is None or self._segment_enum is None:
            self.add_paragraph("Browsing is unavailable — the catalogue could not be opened.")
            return

        self._syncing = False
        self._search = ""
        self._window_limit = 200

        self._segments: dict[str, Any] = {}
        compat.append(self, self._build_segment_switch())

        self._filter_bar = FilterBar(
            orientation_enum=self.context.orientation,
            aspect_enum=self.context.aspect,
            on_search=self._on_search,
            on_orientation=self._vm.set_orientation,
            on_aspect=self._vm.set_aspect,
            on_min_long_edge=self._vm.set_min_long_edge,
        )
        compat.append(self, self._filter_bar)

        self._grid = ImageGrid(self._vm.load_thumb, on_need_more=self._need_more)
        compat.append(self, self._grid, expand=True)

        self._vm.add_observer(self._on_state)
        self._vm.refresh()

    # -- segment switch ---------------------------------------------------------------------------------

    def _build_segment_switch(self) -> Any:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        compat.add_class(box, "segment-switch")
        labels = (
            (self._segment_enum.ALL, "All"),
            (self._segment_enum.IDEAL, "Ideal for this desktop"),
            (self._segment_enum.NEAR_MISS, "Near misses"),
        )
        for segment, label in labels:
            button = Gtk.ToggleButton(label=label)
            compat.add_class(button, "segment")
            button.connect("toggled", self._segment_toggled, segment)
            self._segments[segment.value] = button
            compat.append(box, button)
        return box

    def _segment_toggled(self, button: Any, segment: Any) -> None:
        if self._syncing or not button.get_active():
            return
        self._vm.set_segment(segment)

    # -- filters ----------------------------------------------------------------------------------------

    def _on_search(self, text: str) -> None:
        self._search = text
        self._vm.set_search(text)

    def _need_more(self) -> None:
        state = self._vm.state
        if len(state.cards) < state.total and self._window_limit < 600:
            self._window_limit = min(600, self._window_limit + 200)
            self._vm.set_window(offset=0, limit=self._window_limit)

    # -- view-model observer ----------------------------------------------------------------------------

    def _on_state(self, state: Any) -> None:
        self._sync_segments(state)
        if state.cards:
            self._grid.set_cards(state.cards)
        else:
            self._grid.show_empty(self._empty_state(state))

    def _sync_segments(self, state: Any) -> None:
        self._syncing = True
        counts = {
            self._segment_enum.ALL.value: state.counts.all,
            self._segment_enum.IDEAL.value: state.counts.ideal,
            self._segment_enum.NEAR_MISS.value: state.counts.near,
        }
        for value, button in self._segments.items():
            button.set_active(value == state.segment)
            base = button.get_label().split("  ")[0]
            button.set_label(f"{base}  {counts.get(value, 0):,}")
        self._syncing = False

    def _empty_state(self, state: Any) -> Any:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.XSMALL)
        compat.add_class(card, "card", "empty-state")
        heading = Gtk.Label(label="No images match")
        heading.set_xalign(0)
        compat.add_class(heading, "hero-title")
        compat.append(card, heading)

        active = self._active_filters(state)
        detail = "Nothing has been scanned yet — open Sources and scan a folder."
        if state.counts.all > 0:
            detail = "No image passes the active filters: " + ", ".join(active) if active else (
                "No image is in this segment yet."
            )
        body = Gtk.Label(label=detail)
        body.set_xalign(0)
        compat.set_wrap(body)
        compat.add_class(body, "dim")
        compat.append(card, body)
        return card

    def _active_filters(self, state: Any) -> list[str]:
        names = {
            self._segment_enum.ALL.value: "All",
            self._segment_enum.IDEAL.value: "Ideal for this desktop",
            self._segment_enum.NEAR_MISS.value: "Near misses",
        }
        active = [names.get(state.segment, state.segment)]
        if state.search:
            active.append(f'search “{state.search}”')
        return active
