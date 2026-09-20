"""GNOME / Budgie / Unity backend — org.gnome.desktop.background."""

from __future__ import annotations

import os
import shutil

from ._gsettings import GSettingsBackend


class GnomeBackend(GSettingsBackend):
    name = "GNOME"
    schema = "org.gnome.desktop.background"
    uri_key = "picture-uri"
    dark_key = "picture-uri-dark"
    options_key = "picture-options"

    def detect(self) -> float:
        desk = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        score = 0.0
        if any(k in desk for k in ("gnome", "budgie", "unity")):
            # Cinnamon also ships the gnome schema; keep this below Cinnamon.
            score += 0.5
        if shutil.which("gnome-shell"):
            score += 0.1
        if self._schema_present():
            score += 0.15
        return min(score, 0.95)
