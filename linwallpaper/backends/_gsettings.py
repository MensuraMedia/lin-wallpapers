"""Shared base for single-background desktops driven by gsettings.

Cinnamon / GNOME / MATE all expose exactly one background image plus a
``picture-options`` mode. Per-monitor targeting is done with the composite trick
(A6): render a canvas spanning the whole layout and set it ``spanned``.
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
from pathlib import Path
from typing import ClassVar
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url

from PIL import Image

from .. import imaging
from .base import ApplyResult, Runner, default_runner


def path_to_uri(path: str) -> str:
    return "file://" + pathname2url(str(Path(path).resolve()))


def uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        return unquote(urlparse(uri).path)
    return uri


class GSettingsBackend:
    """Base class; subclasses set the schema/keys and implement ``detect``."""

    name = "gsettings"
    supports_per_monitor = False  # not natively; via composite
    schema = ""
    uri_key = "picture-uri"
    options_key = "picture-options"
    dark_key: str | None = None
    uri_is_path = False  # MATE stores a bare path, not a file:// uri
    spanned_value = "spanned"
    # canonical fit -> desktop picture-options value
    option_map: ClassVar[dict[str, str]] = {
        imaging.FIT_FILL: "zoom",
        imaging.FIT_FIT: "scaled",
        imaging.FIT_CENTER: "centered",
        imaging.FIT_STRETCH: "stretched",
    }

    def __init__(self, runner: Runner | None = None) -> None:
        self._run = runner or default_runner

    # ---- helpers ----------------------------------------------------------
    def _get(self, key: str) -> str:
        raw = self._run(["gsettings", "get", self.schema, key])
        return raw.strip().strip("'\"")

    def _set(self, key: str, value: str) -> None:
        self._run(["gsettings", "set", self.schema, key, value])

    def _store_value(self, path: str) -> str:
        return path if self.uri_is_path else path_to_uri(path)

    def _has_gsettings(self) -> bool:
        return shutil.which("gsettings") is not None

    def _schema_present(self) -> bool:
        try:
            out = self._run(["gsettings", "list-schemas"])
            return self.schema in out.split()
        except Exception:
            return False

    # ---- protocol ---------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if not self._has_gsettings():
            return False, "no-gsettings"
        if not self._schema_present():
            return False, "schema-missing"
        return True, "ok"

    def current(self) -> dict:
        state = {self.uri_key: self._get(self.uri_key), self.options_key: self._get(self.options_key)}
        if self.dark_key:
            state[self.dark_key] = self._get(self.dark_key)
        return state

    def _current_image_path(self) -> str | None:
        try:
            raw = self._get(self.uri_key)
        except Exception:
            return None
        if not raw:
            return None
        p = raw if self.uri_is_path else uri_to_path(raw)
        return p if p and Path(p).exists() else None

    def apply(self, image: str, fit: str, monitors: list, target: str = "all") -> ApplyResult:
        previous = self.current()
        if target == "all" or len(monitors) <= 1 or not any(m.name == target for m in monitors):
            store = self._store_value(image)
            self._set(self.uri_key, store)
            if self.dark_key:
                self._set(self.dark_key, store)
            self._set(self.options_key, self.option_map.get(fit, "zoom"))
            note = "all screens"
        else:
            composite = self._composite(image, fit, monitors, target)
            store = self._store_value(composite)
            self._set(self.uri_key, store)
            if self.dark_key:
                self._set(self.dark_key, store)
            self._set(self.options_key, self.spanned_value)
            note = f"composite ({target})"
        return ApplyResult(
            backend=self.name, target=target, fit=fit, image=image, previous=previous, note=note
        )

    def restore(self, previous: dict) -> None:
        for key, value in previous.items():
            self._set(key, value)

    # ---- composite (A6) ---------------------------------------------------
    def _composite(self, image: str, fit: str, monitors: list, target: str) -> str:
        from ..monitors import layout_bounds

        min_x, min_y, total_w, total_h = layout_bounds(monitors)
        canvas = Image.new("RGB", (max(1, total_w), max(1, total_h)), (18, 20, 26))

        # Fill the whole canvas with the current background so untargeted
        # monitors keep showing what they already show.
        cur = self._current_image_path()
        if cur:
            with contextlib.suppress(Exception):
                canvas = imaging.transform(cur, (max(1, total_w), max(1, total_h)), imaging.FIT_FILL)

        for mon in monitors:
            if mon.name != target:
                continue
            rx = mon.x * mon.scale - min_x
            ry = mon.y * mon.scale - min_y
            tile = imaging.transform(image, (mon.px_width, mon.px_height), fit)
            canvas.paste(tile, (rx, ry))

        out_dir = Path.home() / ".cache" / "linwallpaper"
        out_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(f"{image}|{fit}|{target}".encode()).hexdigest()[:12]
        out = out_dir / f"composite-{digest}.png"
        canvas.save(out, "PNG")
        return str(out)
