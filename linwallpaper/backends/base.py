"""Wallpaper backend protocol + evidence-based registry.

No branch on a distribution/release/desktop *name* outside a backend's ``detect()``.
Backends shell out to the desktop's own tools through an injectable ``runner`` so
they are trivially unit-testable with a fake root and no real system.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# A runner: argv -> completed text output. Injectable for tests.
Runner = Callable[[list[str]], str]


def default_runner(argv: list[str]) -> str:
    """Run a command and return stripped stdout; raise on failure."""
    res = subprocess.run(
        argv, capture_output=True, text=True, check=True, timeout=15
    )
    return res.stdout.strip()


@dataclass
class ApplyResult:
    """What an apply did, and how to undo it."""

    backend: str
    target: str  # "all" or a connector name
    fit: str
    image: str
    previous: dict = field(default_factory=dict)  # opaque state for restore()
    note: str = ""


@runtime_checkable
class WallpaperBackend(Protocol):
    name: str
    supports_per_monitor: bool

    def detect(self) -> float:
        """Confidence 0.0..1.0 that this backend drives the current session."""
        ...

    def available(self) -> tuple[bool, str]:
        """(usable, reason) — a reason code when greyed out."""
        ...

    def current(self) -> dict:
        """Read the current wallpaper state (for display + undo)."""
        ...

    def apply(self, image: str, fit: str, monitors: list, target: str = "all") -> ApplyResult:
        """Apply ``image`` with ``fit`` to ``target`` and return an :class:`ApplyResult`."""
        ...

    def restore(self, previous: dict) -> None:
        """Restore a previous state captured in :attr:`ApplyResult.previous`."""
        ...


_REGISTRY: list[WallpaperBackend] = []


def register(backend: WallpaperBackend) -> WallpaperBackend:
    _REGISTRY.append(backend)
    return backend


def all_backends() -> list[WallpaperBackend]:
    return list(_REGISTRY)


def detect_backend() -> WallpaperBackend | None:
    """Pick the highest-confidence backend; ``None`` if nothing scores > 0."""
    best: WallpaperBackend | None = None
    best_score = 0.0
    for be in _REGISTRY:
        try:
            score = be.detect()
        except Exception:
            score = 0.0
        if score > best_score:
            best, best_score = be, score
    return best
