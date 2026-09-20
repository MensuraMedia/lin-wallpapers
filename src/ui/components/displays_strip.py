"""The detected-displays strip on the Sources page (M1 §2.9, §15).

Shows one chip per target display ("HDMI-1 · 1920×1080"), or — when nothing was detected — the
``DISPLAY_NOT_DETECTED`` reason text the view model supplies, never a silent blank. Fed the
``DisplaysStrip`` DTO only.
"""

from __future__ import annotations

from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat


class DisplaysStrip(Gtk.Box):  # type: ignore[misc]
    """A row of display chips (or the not-detected reason); call :meth:`update` with the DTO."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.XSMALL)
        compat.add_class(self, "card", "displays-strip")

        eyebrow = Gtk.Label()
        compat.set_tracked_text(eyebrow, "SCREENS")
        eyebrow.set_xalign(0)
        compat.add_class(eyebrow, "eyebrow")
        compat.append(self, eyebrow)

        self._body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.SMALL)
        compat.append(self, self._body)

    def update(self, strip: Any) -> None:
        compat.clear_children(self._body)
        if strip.displays:
            for display in strip.displays:
                compat.append(self._body, self._chip(display))
        else:
            reason = Gtk.Label(label=strip.empty_text or "No display detected.")
            reason.set_xalign(0)
            compat.set_wrap(reason)
            compat.add_class(reason, "dim")
            compat.add_class(self._body, "warn")
            compat.append(self._body, reason)
        compat.show(self)

    def _chip(self, display: Any) -> Any:
        text = f"{display.name} · {display.width}×{display.height}"
        if display.primary:
            text += " (primary)"
        chip = Gtk.Label(label=text)
        compat.add_class(chip, "chip", "tabular")
        return chip
