"""Shared, gi-free app state with a tiny observer mechanism.

Pages read from and mutate this; they subscribe to ``on_change`` to refresh.
Keeping it separate from widgets keeps the viewmodel testable.
"""

from __future__ import annotations

from collections.abc import Callable

from .. import imaging


class AppState:
    def __init__(self, backend, monitors, desktop) -> None:
        self.backend = backend
        self.monitors = monitors
        self.desktop = desktop
        self.image_path: str | None = None
        self.fit: str = imaging.FIT_FILL
        self.target: str = "all"  # "all" or a connector name
        self.per_screen: dict[str, str] = {}  # connector -> image path
        # Per-surface image OVERRIDES, keyed by surface key (connector/lock/login…).
        # A surface with no entry here falls back to the global ``image_path``.
        self.surface_image: dict[str, str] = {}
        self.applied: dict[str, str] = {}  # target ("all"/connector) -> applied image path
        self.last_apply = None  # ApplyResult, for Undo
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def notify(self) -> None:
        for fn in list(self._listeners):
            fn()

    # mutations
    def set_image(self, path: str) -> None:
        self.image_path = path
        self.notify()

    def set_fit(self, fit: str) -> None:
        if fit in imaging.FITS:
            self.fit = fit
            self.notify()

    def set_target(self, target: str) -> None:
        self.target = target
        self.notify()

    # ---- per-surface image overrides -------------------------------------
    def resolved_image(self, key: str) -> str | None:
        """The image a surface uses: its own override if set, else the global one."""
        return self.surface_image.get(key) or self.image_path

    def set_surface_image(self, key: str, path: str) -> None:
        """Give one surface its own image (does not touch the global image)."""
        self.surface_image[key] = path

    def clear_surface_images(self) -> None:
        """Drop every per-surface override so all surfaces follow the global image."""
        self.surface_image.clear()
