"""File-manager context-menu providers and evidence-based detection.

Mirrors ``linwallpaper.backends``: ``detect_context_provider()`` returns the
highest-confidence provider for the active file manager, or ``None``.
"""

from __future__ import annotations

from .base import ContextMenuProvider, default_exec_cmd
from .dolphin import DolphinProvider
from .nautilus import NautilusProvider
from .nemo import NemoProvider
from .thunar import ThunarProvider

__all__ = [
    "ContextMenuProvider",
    "all_context_providers",
    "default_exec_cmd",
    "detect_context_provider",
]


def all_context_providers() -> list[ContextMenuProvider]:
    return [NemoProvider(), NautilusProvider(), ThunarProvider(), DolphinProvider()]


def detect_context_provider() -> ContextMenuProvider | None:
    """The most-likely-active file manager's provider, by confidence, or None."""
    best: ContextMenuProvider | None = None
    best_conf = 0.0
    for provider in all_context_providers():
        conf = provider.detect()
        # An already-installed action breaks ties toward the one in use.
        if provider.is_installed():
            conf = max(conf, 0.5) + 0.1
        if conf > best_conf:
            best, best_conf = provider, conf
    return best if best_conf > 0.0 else None
