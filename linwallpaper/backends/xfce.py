"""Xfce backend — xfconf-query, one image key per monitor (native per-monitor)."""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

from .. import imaging
from .base import ApplyResult, Runner, default_runner

# xfce image-style ints: 0 none,1 centered,2 tiled,3 stretched,4 scaled,5 zoomed
_STYLE = {
    imaging.FIT_CENTER: "1",
    imaging.FIT_STRETCH: "3",
    imaging.FIT_FIT: "4",
    imaging.FIT_FILL: "5",
}


class XfceBackend:
    name = "Xfce"
    supports_per_monitor = True

    def __init__(self, runner: Runner | None = None) -> None:
        self._run = runner or default_runner

    def detect(self) -> float:
        desk = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        score = 0.0
        if "xfce" in desk:
            score += 0.6
        if shutil.which("xfconf-query"):
            score += 0.35
        return min(score, 1.0)

    def available(self) -> tuple[bool, str]:
        if shutil.which("xfconf-query") is None:
            return False, "no-xfconf-query"
        return True, "ok"

    def _props(self) -> list[str]:
        out = self._run(["xfconf-query", "-c", "xfce4-desktop", "-l"])
        return [ln.strip() for ln in out.splitlines() if ln.strip().endswith("last-image")]

    def current(self) -> dict:
        state = {}
        try:
            for prop in self._props():
                try:
                    state[prop] = self._run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop])
                except Exception:
                    state[prop] = ""
        except Exception:
            pass
        return state

    def apply(self, image: str, fit: str, monitors: list, target: str = "all") -> ApplyResult:
        previous = self.current()
        props = self._props()
        chosen = props
        if target != "all":
            chosen = [p for p in props if f"monitor{target}" in p or f"/{target}/" in p] or props
        abs_image = str(Path(image).resolve())
        for prop in chosen:
            self._run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", abs_image])
            style_prop = prop.replace("last-image", "image-style")
            self._run(
                ["xfconf-query", "-c", "xfce4-desktop", "-p", style_prop, "-s", _STYLE.get(fit, "5")]
            )
        return ApplyResult(
            backend=self.name, target=target, fit=fit, image=image, previous=previous, note="xfconf"
        )

    def restore(self, previous: dict) -> None:
        for prop, value in previous.items():
            if value:
                with contextlib.suppress(Exception):
                    self._run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", value])
