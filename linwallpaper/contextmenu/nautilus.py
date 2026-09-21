"""Nautilus (GNOME) — a user script in the Nautilus scripts directory.

Nautilus passes the selection to scripts via ``$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS``
(newline-separated). The script forwards them to the add-CLI.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import ACTION_LABEL, ContextMenuProvider


def _scripts_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "nautilus" / "scripts"


class NautilusProvider(ContextMenuProvider):
    binary = "nautilus"
    name = "Files (Nautilus)"
    desktop_hints = ("gnome", "unity", "budgie")

    @property
    def _file(self) -> Path:
        return _scripts_dir() / ACTION_LABEL

    def is_installed(self) -> bool:
        return self._file.is_file()

    def install(self, exec_cmd: str | None = None) -> None:
        text = (
            "#!/usr/bin/env bash\n"
            "# Add to LinWallpaper — Nautilus script\n"
            "set -eu\n"
            "paths=()\n"
            'if [ -n "${NAUTILUS_SCRIPT_SELECTED_FILE_PATHS:-}" ]; then\n'
            '  while IFS= read -r p; do [ -n "$p" ] && paths+=("$p"); done '
            '<<< "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"\n'
            "fi\n"
            f'{self._exec(exec_cmd)} "${{paths[@]}}"\n'
        )
        self._write(self._file, text, mode=0o755)

    def uninstall(self) -> None:
        self._remove(self._file)
