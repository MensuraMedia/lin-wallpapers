"""Live scan progress banner (M1 acceptance #2), bound to ``ScanVM``'s frozen ``ScanState``.

Shows the running counts ("2,140 found · 830 probed · 212 ideal") and a Cancel button while a scan
runs, and hides itself otherwise. It reads only the DTO fields, never a scanner type.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat


class ScanBanner(Gtk.Box):  # type: ignore[misc]
    """A one-line progress strip; call :meth:`update` with a ``ScanState`` on every change."""

    def __init__(self, on_cancel: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.SMALL)
        compat.add_class(self, "scan-banner")
        self.set_no_show_all(True)  # gtk4-lint: ok — visibility is driven by update(), never show_all
        self.set_visible(False)

        self._spinner = Gtk.Spinner()
        compat.append(self, self._spinner)

        self._label = Gtk.Label(label="")
        self._label.set_xalign(0)
        self._label.set_hexpand(True)
        compat.add_class(self._label, "tabular")
        compat.append(self, self._label, expand=True)

        self._cancel = Gtk.Button(label="Cancel")
        compat.add_class(self._cancel, "pill")
        self._cancel.connect("clicked", lambda _button: on_cancel())
        compat.append(self, self._cancel)

    def update(self, state: Any) -> None:
        if not state.running:
            self._spinner.stop()
            self.set_visible(False)
            return
        self.set_visible(True)
        self._spinner.start()
        parts = [
            f"{state.found:,} found",
            f"{state.probed:,} probed",
            f"{state.ideal:,} ideal",
        ]
        if state.excluded:
            parts.append(f"{state.excluded:,} skipped")
        if state.current_dir:
            parts.append(state.current_dir)
        self._label.set_text(" · ".join(parts))
