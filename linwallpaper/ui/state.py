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
