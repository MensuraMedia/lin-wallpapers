"""Stroke glyphs for the sidebar routes, drawn on the mockups' 24-unit grid (docs/mockups/Sidebar.dc.html).

Symbolic theme icons differ per desktop (filled in Mint-Y, outlined in Yaru); these look the same
everywhere and take the button's CSS ``color``, so hover and active states recolor them.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import cairo

from src.gtk_version import Gtk
from src.ui import compat

GRID = 24.0
STROKE = 1.9


def rounded_rect(cr: Any, x: float, y: float, width: float, height: float, radius: float) -> None:
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _polyline(cr: Any, *points: tuple[float, float]) -> None:
    cr.move_to(*points[0])
    for point in points[1:]:
        cr.line_to(*point)


def _browse(cr: Any) -> None:
    for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
        rounded_rect(cr, x, y, 7, 7, 1.5)
    cr.stroke()


def _image(cr: Any) -> None:
    rounded_rect(cr, 3, 4, 18, 16, 2)
    _polyline(cr, (3, 15), (8, 10.5), (12, 14), (15.5, 10), (21, 15))
    cr.stroke()


def _screens(cr: Any) -> None:
    # The back screen is clipped where the front one overlaps it, instead of being painted over.
    cr.save()
    cr.rectangle(0, 0, GRID, 10)
    cr.rectangle(0, 10, 8, GRID - 10)
    cr.clip()
    rounded_rect(cr, 2, 4, 14, 10, 1.6)
    cr.stroke()
    cr.restore()
    rounded_rect(cr, 9, 11, 13, 9, 1.6)
    cr.stroke()


def _preview(cr: Any) -> None:
    cr.move_to(2, 12)
    cr.curve_to(5.6, 5.5, 8, 5.5, 12, 5.5)
    cr.curve_to(16, 5.5, 18.4, 5.5, 22, 12)
    cr.curve_to(18.4, 18.5, 16, 18.5, 12, 18.5)
    cr.curve_to(8, 18.5, 5.6, 18.5, 2, 12)
    cr.close_path()
    cr.new_sub_path()
    cr.arc(12, 12, 2.6, 0, 2 * math.pi)
    cr.stroke()


def _sources(cr: Any) -> None:
    cr.move_to(3, 7.5)
    cr.arc(4.5, 7.5, 1.5, math.pi, 3 * math.pi / 2)
    cr.line_to(8.5, 6)
    cr.line_to(10.5, 8.5)
    cr.line_to(19.5, 8.5)
    cr.arc(19.5, 10, 1.5, -math.pi / 2, 0)
    cr.line_to(21, 17.5)
    cr.arc(19.5, 17.5, 1.5, 0, math.pi / 2)
    cr.line_to(4.5, 19)
    cr.arc(4.5, 17.5, 1.5, math.pi / 2, math.pi)
    cr.close_path()
    cr.stroke()


def _collections(cr: Any) -> None:
    for y, x0, x1 in ((7, 4, 20), (11, 6, 18), (15, 8, 16), (19, 10, 14)):
        _polyline(cr, (x0, y), (x1, y))
    cr.stroke()


def _history(cr: Any) -> None:
    _polyline(cr, (12, 7), (12, 12), (15, 14))
    cr.new_sub_path()
    cr.arc(12, 12, 9, 0, 2 * math.pi)
    cr.stroke()


def _settings(cr: Any) -> None:
    cr.arc(12, 12, 3, 0, 2 * math.pi)
    rays = (
        ((12, 3), (12, 5)),
        ((12, 19), (12, 21)),
        ((4.9, 7), (6.6, 8)),
        ((17.4, 16), (19.1, 17)),
        ((4.9, 17), (6.6, 16)),
        ((17.4, 8), (19.1, 7)),
        ((3, 12), (5, 12)),
        ((19, 12), (21, 12)),
    )
    for start, end in rays:
        _polyline(cr, start, end)
    cr.stroke()


def _test(cr: Any) -> None:
    # A laboratory flask: neck, body and a liquid line — the Test (verification) page.
    _polyline(cr, (9, 4), (9, 9), (4.5, 19), (19.5, 19), (15, 9), (15, 4))
    _polyline(cr, (8, 4), (16, 4))
    _polyline(cr, (7, 14), (17, 14))
    cr.stroke()


GLYPHS: dict[str, Callable[[Any], None]] = {
    "browse": _browse,
    "image": _image,
    "screens": _screens,
    "preview": _preview,
    "sources": _sources,
    "collections": _collections,
    "history": _history,
    "settings": _settings,
    "test": _test,
}


class NavGlyph(compat.CanvasArea):
    """One route glyph at ``size`` px, stroked in the inherited foreground color."""

    def __init__(self, route: str, size: int) -> None:
        super().__init__(size, size)
        self.draw_glyph = GLYPHS[route]
        self.set_valign(Gtk.Align.CENTER)
        compat.add_class(self, "nav-glyph")

    def on_draw(self, cr: Any, width: int, height: int) -> None:
        size = min(width, height)
        cr.translate((width - size) / 2, (height - size) / 2)
        cr.scale(size / GRID, size / GRID)
        cr.set_source_rgba(*compat.foreground_color(self))
        cr.set_line_width(STROKE)
        cr.set_line_cap(cairo.LineCap.ROUND)
        cr.set_line_join(cairo.LineJoin.ROUND)
        self.draw_glyph(cr)
