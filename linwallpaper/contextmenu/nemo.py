"""Nemo (Cinnamon) — a ``.nemo_action`` in the user's actions directory.

Nemo hot-loads actions from ``~/.local/share/nemo/actions/`` with no restart.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import APP_ID
from .base import ACTION_COMMENT, ACTION_EXTS, ACTION_LABEL, ContextMenuProvider


def _actions_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "nemo" / "actions"


class NemoProvider(ContextMenuProvider):
    binary = "nemo"
    name = "Nemo"
    desktop_hints = ("cinnamon", "x-cinnamon", "nemo")

    @property
    def _file(self) -> Path:
        return _actions_dir() / "linwallpaper-add.nemo_action"

    def is_installed(self) -> bool:
        return self._file.is_file()

    def install(self, exec_cmd: str | None = None) -> None:
        exts = ";".join(ACTION_EXTS) + ";dir;"
        text = (
            "[Nemo Action]\n"
            f"Name={ACTION_LABEL}\n"
            f"Comment={ACTION_COMMENT}\n"
            f"Exec={self._exec(exec_cmd)} %F\n"
            f"Icon-Name={APP_ID}\n"
            "Selection=NotNone\n"
            f"Extensions={exts}\n"
            "Quote=double\n"
        )
        self._write(self._file, text)

    def uninstall(self) -> None:
        self._remove(self._file)
