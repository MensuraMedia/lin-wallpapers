"""Dolphin (KDE) — a KIO service menu ``.desktop`` file.

Placed in ``~/.local/share/kio/servicemenus/``; Dolphin offers it on images and
folders. Newer KDE reads this location directly (no root, no rebuild).
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import APP_ID
from .base import ACTION_COMMENT, ACTION_LABEL, ContextMenuProvider


def _servicemenus_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "kio" / "servicemenus"


_MIME = "image/jpeg;image/png;image/webp;image/bmp;image/gif;image/tiff;inode/directory;"


class DolphinProvider(ContextMenuProvider):
    binary = "dolphin"
    name = "Dolphin (KDE)"
    desktop_hints = ("kde", "plasma")

    @property
    def _file(self) -> Path:
        return _servicemenus_dir() / "linwallpaper-add.desktop"

    def is_installed(self) -> bool:
        return self._file.is_file()

    def install(self, exec_cmd: str | None = None) -> None:
        text = (
            "[Desktop Entry]\n"
            "Type=Service\n"
            f"MimeType={_MIME}\n"
            "Actions=addToLinWallpaper;\n"
            "X-KDE-Priority=TopLevel\n"
            "\n"
            "[Desktop Action addToLinWallpaper]\n"
            f"Name={ACTION_LABEL}\n"
            f"Comment={ACTION_COMMENT}\n"
            f"Icon={APP_ID}\n"
            f"Exec={self._exec(exec_cmd)} %F\n"
        )
        self._write(self._file, text, mode=0o755)

    def uninstall(self) -> None:
        self._remove(self._file)
