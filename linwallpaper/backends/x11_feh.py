"""Generic X11 fallback — feh --bg-* (one image argument per output).

Best-effort: feh has no readback, so Undo is limited to re-running with the
previously-known image if the app captured one this session.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .. import imaging
from .base import ApplyResult, Runner, default_runner

_MODE = {
    imaging.FIT_FILL: "--bg-fill",
    imaging.FIT_FIT: "--bg-max",
    imaging.FIT_CENTER: "--bg-center",
    imaging.FIT_STRETCH: "--bg-scale",
}


class FehBackend:
    name = "X11 (feh)"
    supports_per_monitor = True  # via per-output image arguments

    def __init__(self, runner: Runner | None = None) -> None:
        self._run = runner or default_runner
        self._last: dict = {}

    def detect(self) -> float:
        # Only a weak fallback: requires X11 and feh, and no stronger DE claimed it.
        if os.environ.get("WAYLAND_DISPLAY"):
            return 0.0
        if not os.environ.get("DISPLAY"):
            return 0.0
        return 0.2 if shutil.which("feh") else 0.0

    def available(self) -> tuple[bool, str]:
        if shutil.which("feh") is None:
            return False, "no-feh"
        return True, "ok"

    def current(self) -> dict:
        # feh writes ~/.fehbg; keep it verbatim for undo.
        fehbg = Path.home() / ".fehbg"
        try:
            return {"fehbg": fehbg.read_text(encoding="utf-8")}
        except OSError:
            return {}

    def apply(self, image: str, fit: str, monitors: list, target: str = "all") -> ApplyResult:
        previous = self.current()
        self._run(["feh", _MODE.get(fit, "--bg-fill"), str(Path(image).resolve())])
        return ApplyResult(
            backend=self.name, target=target, fit=fit, image=image, previous=previous, note="feh"
        )

    def restore(self, previous: dict) -> None:
        # Re-run the saved ~/.fehbg script if present.
        script = previous.get("fehbg")
        if script:
            self._run(["sh", "-c", script])
