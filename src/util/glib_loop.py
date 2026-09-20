"""GUI-side scheduler: deliver a worker's result on the GLib main loop.

Kept apart from ``util/threads.py`` so the service layers (scanner, catalogue, cli) can use the
worker pattern without importing ``gi``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gi.repository import GLib


def glib_scheduler(callback: Callable[[], Any]) -> None:
    """Deliver ``callback`` once, on the GLib main loop."""

    def _once() -> bool:
        callback()
        return False  # GLib.SOURCE_REMOVE

    GLib.idle_add(_once)
