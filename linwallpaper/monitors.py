"""Monitor detection: Gdk.Monitor -> frozen MonitorInfo DTOs.

This is the only module besides ``ui/`` and ``main.py`` that touches ``gi``.
It exposes plain dataclasses so everything downstream stays gi-free and testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MonitorInfo:
    """A plain, hashable description of one physical monitor."""

    name: str
    width: int  # logical width
    height: int  # logical height
    scale: int
    x: int
    y: int
    primary: bool
    model: str = ""

    @property
    def px_width(self) -> int:
        return self.width * self.scale

    @property
    def px_height(self) -> int:
        return self.height * self.scale

    @property
    def resolution(self) -> str:
        return f"{self.px_width} × {self.px_height}"


def list_monitors() -> list[MonitorInfo]:
    """Return the currently attached monitors as :class:`MonitorInfo` DTOs.

    Requires a display connection; raises if called headless.
    """
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    if display is None:
        return []
    model = display.get_monitors()
    primary_conn = _primary_connector(display)
    out: list[MonitorInfo] = []
    for i in range(model.get_n_items()):
        mon = model.get_item(i)
        geo = mon.get_geometry()
        conn = mon.get_connector() or f"screen-{i}"
        out.append(
            MonitorInfo(
                name=conn,
                width=geo.width,
                height=geo.height,
                scale=mon.get_scale_factor(),
                x=geo.x,
                y=geo.y,
                primary=(conn == primary_conn) if primary_conn else (i == 0),
                model=mon.get_model() or "",
            )
        )
    return out


def _primary_connector(display) -> str | None:
    """Best-effort primary detection (GTK 4 dropped an explicit primary API)."""
    try:
        model = display.get_monitors()
        if model.get_n_items():
            # Heuristic: the monitor at the layout origin (0,0) is primary.
            for i in range(model.get_n_items()):
                mon = model.get_item(i)
                geo = mon.get_geometry()
                if geo.x == 0 and geo.y == 0:
                    return mon.get_connector()
    except Exception:
        pass
    return None


def layout_bounds(monitors: list[MonitorInfo]) -> tuple[int, int, int, int]:
    """Return (min_x, min_y, total_width, total_height) of the monitor layout in px."""
    if not monitors:
        return (0, 0, 0, 0)
    min_x = min(m.x * m.scale for m in monitors)
    min_y = min(m.y * m.scale for m in monitors)
    max_x = max((m.x * m.scale) + m.px_width for m in monitors)
    max_y = max((m.y * m.scale) + m.px_height for m in monitors)
    return (min_x, min_y, max_x - min_x, max_y - min_y)


def desktop_name() -> str:
    """A human string for the current desktop + session type, e.g. 'Cinnamon · X11'."""
    desk = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        .replace("X-", "")
        .split(":")[0]
        .strip()
    )
    if not desk:
        desk = os.environ.get("DESKTOP_SESSION", "Unknown").title()
    session = "Wayland" if os.environ.get("WAYLAND_DISPLAY") else "X11"
    return f"{desk or 'Unknown'} · {session}"
