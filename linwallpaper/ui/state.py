"""Shared, gi-free app state with a tiny observer mechanism.

Pages read from and mutate this; they subscribe to ``on_change`` to refresh.
Keeping it separate from widgets keeps the viewmodel testable.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from .. import imaging
from ..collection import Collection
from ..config import Settings

# The privileged (root-owned) surfaces whose last-applied image is persisted:
# the app cannot read these back from the system, so we remember what we wrote.
_PRIVILEGED_SURFACES = ("login", "splash", "grub")


def _default_config_dir() -> Path:
    """``$XDG_CONFIG_HOME/linwallpaper`` (or ``~/.config/linwallpaper``)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "linwallpaper"


class AppState:
    def __init__(self, backend, monitors, desktop, config_dir=None) -> None:
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
        # Persisted last-applied image/fit for the privileged surfaces only.
        self._config_dir = Path(config_dir) if config_dir else _default_config_dir()
        self._applied_file = self._config_dir / "applied.json"
        self._applied_persisted: dict[str, dict] = self._load_applied()
        # The wallpaper library and the small settings store (both gi-free).
        self.collection = Collection()
        self.settings = Settings(self._config_dir)

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

    # ---- persisted last-applied image (privileged surfaces only) ----------
    def _load_applied(self) -> dict[str, dict]:
        """Read ``applied.json``; tolerate a missing/corrupt file (→ empty)."""
        try:
            data = json.loads(self._applied_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, dict] = {}
        for surface in _PRIVILEGED_SURFACES:
            entry = data.get(surface)
            if isinstance(entry, dict) and isinstance(entry.get("image"), str):
                fit = entry.get("fit")
                out[surface] = {
                    "image": entry["image"],
                    "fit": fit if fit in imaging.FITS else imaging.FIT_FILL,
                }
        return out

    def _save_applied(self) -> None:
        """Write ``applied.json`` atomically (temp + replace); dir mode 0700."""
        try:
            self._config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            tmp = self._applied_file.with_name(self._applied_file.name + ".tmp")
            tmp.write_text(json.dumps(self._applied_persisted, indent=2), encoding="utf-8")
            tmp.replace(self._applied_file)
        except OSError:
            pass

    def record_applied(self, surface: str, image: str, fit: str) -> None:
        """Persist a privileged surface's last-applied image + fit to disk."""
        self._applied_persisted[surface] = {"image": image, "fit": fit}
        self._save_applied()

    def applied_image(self, surface: str) -> str | None:
        """The last-applied image path persisted for ``surface`` (or None)."""
        entry = self._applied_persisted.get(surface)
        return entry.get("image") if entry else None

    def applied_fit(self, surface: str) -> str | None:
        """The fit persisted alongside ``surface``'s last-applied image (or None)."""
        entry = self._applied_persisted.get(surface)
        return entry.get("fit") if entry else None
