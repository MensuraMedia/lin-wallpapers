"""Context-menu provider base — the file-manager "Add to LinWallpaper" seam.

Each file manager has its own way to register a right-click action; per the
project rule (*providers, not conditionals*) each lives behind a provider that
``detect()``s whether it is the active file manager and installs/removes a
user-level entry that invokes ``python3 -m linwallpaper.addcli`` on the
selection. No ``gi`` here — this is service-layer.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path

# The label the user sees in their file manager.
ACTION_LABEL = "Add to LinWallpaper"
ACTION_COMMENT = "Add the selected image(s) to your LinWallpaper library"
# Image extensions the action offers itself on (folders are added separately).
ACTION_EXTS = ("jpg", "jpeg", "png", "webp", "bmp", "gif", "tiff", "tif")


def _checkout_root() -> Path:
    """The directory that contains the ``linwallpaper`` package."""
    return Path(__file__).resolve().parents[2]


def default_exec_cmd() -> str:
    """Command that runs the add-CLI from any working directory.

    Sets ``PYTHONPATH`` to the checkout so ``-m linwallpaper.addcli`` resolves no
    matter what folder the file manager launches the action from.
    """
    root = shlex.quote(str(_checkout_root()))
    py = shlex.quote(sys.executable or "python3")
    return f"env PYTHONPATH={root} {py} -m linwallpaper.addcli"


def _desktop() -> str:
    current = os.environ.get("XDG_CURRENT_DESKTOP", "")
    session = os.environ.get("XDG_SESSION_DESKTOP", "")
    return f"{current} {session}".lower()


class ContextMenuProvider(ABC):
    """One file manager's right-click integration."""

    #: file-manager binary that signals this provider applies
    binary: str = ""
    #: short human name shown in Settings
    name: str = ""
    #: desktop keywords that raise confidence (lowercase)
    desktop_hints: tuple[str, ...] = ()

    def detect(self) -> float:
        """Confidence (0..1) that this is the machine's active file manager."""
        if not shutil.which(self.binary):
            return 0.0
        conf = 0.4  # installed
        if any(h in _desktop() for h in self.desktop_hints):
            conf += 0.5
        return min(conf, 0.95)

    @abstractmethod
    def is_installed(self) -> bool: ...

    @abstractmethod
    def install(self, exec_cmd: str | None = None) -> None: ...

    @abstractmethod
    def uninstall(self) -> None: ...

    # shared helpers -------------------------------------------------------
    def _exec(self, exec_cmd: str | None) -> str:
        return exec_cmd or default_exec_cmd()

    @staticmethod
    def _write(path: Path, text: str, mode: int = 0o644) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(mode)
        tmp.replace(path)

    @staticmethod
    def _remove(path: Path) -> None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
