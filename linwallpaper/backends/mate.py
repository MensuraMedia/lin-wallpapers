"""MATE backend — org.mate.background (stores a bare path, not a URI)."""

from __future__ import annotations

import os
import shutil
from typing import ClassVar

from .. import imaging
from ._gsettings import GSettingsBackend


class MateBackend(GSettingsBackend):
    name = "MATE"
    schema = "org.mate.background"
    uri_key = "picture-filename"
    options_key = "picture-options"
    uri_is_path = True
    option_map: ClassVar[dict[str, str]] = {
        imaging.FIT_FILL: "zoom",
        imaging.FIT_FIT: "scaled",
        imaging.FIT_CENTER: "centered",
        imaging.FIT_STRETCH: "stretched",
    }

    def detect(self) -> float:
        desk = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        score = 0.0
        if "mate" in desk:
            score += 0.6
        if shutil.which("mate-session"):
            score += 0.15
        if self._schema_present():
            score += 0.25
        return min(score, 1.0)
