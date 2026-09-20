"""Backend registry. Import order = tiebreak order; detect() confidence decides."""

from __future__ import annotations

from .base import (
    ApplyResult,
    WallpaperBackend,
    all_backends,
    detect_backend,
    register,
)
from .cinnamon import CinnamonBackend
from .gnome import GnomeBackend
from .mate import MateBackend
from .x11_feh import FehBackend
from .xfce import XfceBackend

# Register default instances (production runner). Higher-specificity DEs first.
register(CinnamonBackend())
register(MateBackend())
register(GnomeBackend())
register(XfceBackend())
register(FehBackend())

__all__ = [
    "ApplyResult",
    "CinnamonBackend",
    "FehBackend",
    "GnomeBackend",
    "MateBackend",
    "WallpaperBackend",
    "XfceBackend",
    "all_backends",
    "detect_backend",
    "register",
]
