"""A reusable simulated-monitor widget.

Draws a fixed-aspect *monitor*: a dark rounded bezel around a screen area, plus a
small stand. The screen shows an image (or a placeholder) at the MONITOR's real
aspect ratio using a :class:`Gtk.AspectFrame` (``obey_child=False``) wrapping a
:class:`Gtk.Picture` in ``COVER`` mode. Because the AspectFrame pins the aspect,
resizing the app/card can never stretch or distort the wallpaper — the monitor
stays proportional and centres within the available space.

``gi`` lives in ``ui/`` by convention, so importing GTK here is allowed.
"""

from __future__ import annotations

from pathlib import Path

from gi.repository import Adw, Gtk

from .imgutil import pil_to_texture, texture_from_file

# Target bezel width in px. Chosen so every sim monitor reads as a real,
# comfortably large display; the AspectFrame keeps it proportional and centred.
_MAX_WIDTH = 460


class MonitorFrame(Gtk.Box):
    """A proportional, non-distorting simulated monitor.

    :param ratio: the monitor's aspect ratio (width / height).
    :param max_width: cap on the bezel width in px; the monitor centres below it.
    """

    def __init__(self, ratio: float = 16 / 9, max_width: int = _MAX_WIDTH) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_halign(Gtk.Align.CENTER)
        self.add_css_class("lw-monitor")
        self._ratio = ratio if ratio and ratio > 0 else 16 / 9
        self._max_width = max_width

        # Adw.Bin is a clean single-child container for the AspectFrame + its
        # bezel styling (padding/border/rounding live in CSS on this widget).
        self._bezel = Adw.Bin()
        self._bezel.add_css_class("lw-monitor-bezel")
        self._bezel.set_halign(Gtk.Align.CENTER)
        bezel = self._bezel

        # The AspectFrame is what guarantees no-stretch: obey_child=False forces
        # the child to the given ratio regardless of how much space we're given.
        # An explicit base size (derived from the ratio) gives it a concrete size
        # to hold; without it an AspectFrame with a shrinkable Picture collapses.
        self._aspect = Gtk.AspectFrame(
            xalign=0.5, yalign=0.5, ratio=self._ratio, obey_child=False
        )

        self._overlay = Gtk.Overlay()
        self._overlay.add_css_class("lw-monitor-screen")
        self._apply_base_size()
        overlay = self._overlay

        self._picture = Gtk.Picture()
        self._picture.set_content_fit(Gtk.ContentFit.COVER)
        self._picture.set_can_shrink(True)
        self._picture.set_hexpand(True)
        self._picture.set_vexpand(True)
        overlay.set_child(self._picture)

        # Placeholder is a bare label centred over the screen; the screen's own
        # background (lw-monitor-screen) shows through when the picture is empty.
        # Using a plain label (not a wrapping label inside a Box) avoids a noisy
        # -1 minimum-height report during constrained height-for-width layout.
        self._placeholder_label = Gtk.Label(label="")
        self._placeholder_label.add_css_class("lw-monitor-placeholder-text")
        self._placeholder_label.set_wrap(True)
        self._placeholder_label.set_max_width_chars(18)
        self._placeholder_label.set_justify(Gtk.Justification.CENTER)
        self._placeholder_label.set_halign(Gtk.Align.CENTER)
        self._placeholder_label.set_valign(Gtk.Align.CENTER)
        overlay.add_overlay(self._placeholder_label)

        self._aspect.set_child(overlay)
        bezel.set_child(self._aspect)
        self.append(bezel)

        # Stand + base beneath the bezel — purely cosmetic, centred. Their sizes
        # scale with the bezel width so the whole monitor stays proportional as
        # the target width changes.
        bezel_w = self._max_width
        stand = Gtk.Box()
        stand.add_css_class("lw-monitor-stand")
        stand.set_halign(Gtk.Align.CENTER)
        stand.set_size_request(round(bezel_w * 0.175), round(bezel_w * 0.037))
        self.append(stand)
        base = Gtk.Box()
        base.add_css_class("lw-monitor-base")
        base.set_halign(Gtk.Align.CENTER)
        base.set_size_request(round(bezel_w * 0.375), round(bezel_w * 0.024))
        self.append(base)

        # Start empty.
        self.set_placeholder("No image")

    # ---- geometry ---------------------------------------------------------
    def _apply_base_size(self) -> None:
        """Pin a concrete base size at the current ratio, capped by max width.

        The height is derived from the width so the monitor is always exactly the
        given aspect; ``halign=CENTER`` then centres it in whatever space it gets.
        """
        base_w = self._max_width
        base_h = max(1, round(base_w / self._ratio))
        self._overlay.set_size_request(base_w, base_h)

    # ---- public API -------------------------------------------------------
    @property
    def ratio(self) -> float:
        return self._ratio

    def set_ratio(self, ratio: float) -> None:
        if ratio and ratio > 0:
            self._ratio = ratio
            self._aspect.set_ratio(ratio)
            self._apply_base_size()

    def set_image(self, src) -> None:
        """Show ``src`` on the screen. Accepts a Pillow image, a path, or None.

        ``None`` clears the picture but leaves any placeholder text in place.
        """
        if src is None:
            self._picture.set_paintable(None)
            self._placeholder_label.set_visible(True)
            return
        try:
            # a str/Path is a file to load; anything else is assumed to be a
            # Pillow image (the shared render).
            texture = (
                texture_from_file(str(src))
                if isinstance(src, (str, Path))
                else pil_to_texture(src)
            )
        except Exception:
            self._picture.set_paintable(None)
            self._placeholder_label.set_visible(True)
            return
        self._picture.set_paintable(texture)
        self._placeholder_label.set_visible(False)

    def set_placeholder(self, text: str) -> None:
        """Put the screen into a neutral placeholder state showing ``text``."""
        self._picture.set_paintable(None)
        self._placeholder_label.set_text(text or "")
        self._placeholder_label.set_visible(True)
