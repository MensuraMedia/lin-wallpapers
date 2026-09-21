"""Privileged (root) apply engine for the login, boot-splash and GRUB surfaces.

The engine itself lives in :mod:`lw_privileged` and is designed to run as a
standalone script under the system ``python3`` (via pkexec/sudo), so it does not
import the rest of the LinWallpaper package. This module only exposes its path
so the UI can locate it.
"""

from __future__ import annotations

from pathlib import Path

HELPER = Path(__file__).resolve().parent / "lw_privileged.py"
