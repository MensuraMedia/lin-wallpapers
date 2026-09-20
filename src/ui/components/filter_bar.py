"""The Browse filter bar (M1 §2.9): search, orientation, aspect and minimum size.

Each control calls back into the page, which forwards to ``BrowseVM``; the enum *classes* are injected
so this widget layer never imports a view-model (let alone a catalogue) type. The view model debounces
and last-wins, so the bar can fire on every keystroke.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat

# (label, value or None). Value is None for the "Any …" reset row.
_MIN_EDGES: tuple[tuple[str, int | None], ...] = (
    ("Any size", None),
    ("1080p +", 1920),
    ("1440p +", 2560),
    ("4K +", 3840),
)


class FilterBar(Gtk.Box):  # type: ignore[misc]
    """A horizontal row of Browse filters, each wired to a plain callback."""

    def __init__(
        self,
        *,
        orientation_enum: Any,
        aspect_enum: Any,
        on_search: Callable[[str], None],
        on_orientation: Callable[[Any | None], None],
        on_aspect: Callable[[Any | None], None],
        on_min_long_edge: Callable[[int | None], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.SMALL)
        compat.add_class(self, "filter-bar")
        self._on_search = on_search
        self._on_orientation = on_orientation
        self._on_aspect = on_aspect
        self._on_min_long_edge = on_min_long_edge

        self._search = Gtk.SearchEntry()
        self._search.set_hexpand(True)
        self._search.set_placeholder_text("Search name or folder")
        self._search.connect("search-changed", lambda entry: on_search(entry.get_text()))
        compat.append(self, self._search, expand=True)

        self._orientations = [None, *list(orientation_enum)]
        self._orientation_combo = self._combo(
            ["Any orientation", *(o.value.capitalize() for o in orientation_enum)],
            self._orientation_changed,
        )
        compat.append(self, self._orientation_combo)

        self._aspects = [None, *list(aspect_enum)]
        self._aspect_combo = self._combo(
            ["Any aspect", *(a.value for a in aspect_enum)], self._aspect_changed
        )
        compat.append(self, self._aspect_combo)

        self._min_combo = self._combo([label for label, _value in _MIN_EDGES], self._min_changed)
        compat.append(self, self._min_combo)

    def _combo(self, labels: list[str], on_changed: Callable[[int], None]) -> Any:
        combo = Gtk.ComboBoxText()
        for label in labels:
            combo.append_text(label)
        combo.set_active(0)
        compat.add_class(combo, "filter-combo")
        combo.connect("changed", lambda box: on_changed(box.get_active()))
        return combo

    def _orientation_changed(self, index: int) -> None:
        self._on_orientation(self._orientations[index] if 0 <= index < len(self._orientations) else None)

    def _aspect_changed(self, index: int) -> None:
        self._on_aspect(self._aspects[index] if 0 <= index < len(self._aspects) else None)

    def _min_changed(self, index: int) -> None:
        self._on_min_long_edge(_MIN_EDGES[index][1] if 0 <= index < len(_MIN_EDGES) else None)
