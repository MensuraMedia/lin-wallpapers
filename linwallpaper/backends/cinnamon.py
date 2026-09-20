"""Cinnamon backend — org.cinnamon.desktop.background."""

from __future__ import annotations

import os
import shutil

from ._gsettings import GSettingsBackend


class CinnamonBackend(GSettingsBackend):
    name = "Cinnamon"
    schema = "org.cinnamon.desktop.background"
    uri_key = "picture-uri"
    options_key = "picture-options"
    # option_map inherited: fill->zoom, fit->scaled, center->centered, stretch->stretched

    def detect(self) -> float:
        desk = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        score = 0.0
        if "cinnamon" in desk:
            score += 0.6
        if shutil.which("cinnamon") or shutil.which("cinnamon-session"):
            score += 0.15
        if self._schema_present():
            score += 0.25
        return min(score, 1.0)
