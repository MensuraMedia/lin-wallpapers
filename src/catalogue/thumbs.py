"""The thumbnail cache (M1 contract §2.8): a JPEG on disk per content key, shrunk and never upscaled.

``ThumbCache`` structurally satisfies ``scanner.probe.ThumbSink`` (``store(image, key, cancel) -> str``)
without importing it — ``scanner`` never imports ``catalogue`` (§1) and the probe lane builds in parallel;
the Protocol is duck-typed, not inherited. Keys are the prober's content hash (D6), always
``^[0-9a-f]{32}$``; this module never computes one, only stores and reads by one.

Ruling Q16: the image handed to :meth:`ThumbCache.store` may already be a reduced-scale (``draft()``)
decode, not the full-resolution original — since a thumbnail is never upscaled here, that is safe. This
module never reads image dimensions as if they were the header dimensions recorded in the catalogue row.

Layout (D13): ``<base>/{normal,large}/<key[:2]>/<key>.jpg``, sharded so no single directory holds more
than a couple of hundred files. Writes are ``*.tmp`` + atomic replace; every directory this module creates
is ``0700`` (the cache lists the user's private image collection by content hash). ``base`` defaults to
``config_paths.thumbs_dir()`` (``<XDG cache dir>/thumbnails``) and nothing is ever written outside it.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import time
from enum import IntEnum
from pathlib import Path
from re import compile as re_compile

from PIL import Image, ImageOps

from src.config import config_paths
from src.util.cancel import CancelToken

_LOG = logging.getLogger(__name__)

DEFAULT_BUDGET_BYTES = 536_870_912
_EVICT_TARGET_FRACTION = 0.9
_TOUCH_INTERVAL_SECONDS = 86_400  # read() bumps mtime (the LRU clock) at most once a day
_KEY_RE = re_compile(r"^[0-9a-f]{32}$")
_MID_GREY = (128, 128, 128)


class ThumbSize(IntEnum):
    NORMAL = 256
    LARGE = 512


def _validate_key(key: str) -> None:
    if not _KEY_RE.match(key):
        raise ValueError(f"not a thumbnail key (expected 32 lower-case hex digits): {key!r}")


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA"):
        return True
    return image.mode == "P" and "transparency" in image.info


def _drop_icc(image: Image.Image) -> Image.Image:
    """Convert to sRGB and drop the embedded profile when that is cheap; otherwise just drop it."""
    icc = image.info.get("icc_profile")
    if not icc:
        return image
    try:
        from PIL import ImageCms

        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        srgb = ImageCms.createProfile("sRGB")
        converted: Image.Image = ImageCms.profileToProfile(image, source, srgb, outputMode="RGB")
    except Exception:  # not cheap (missing lcms, a bogus profile, an unsupported mode) — keep the pixels
        converted = image.copy()
    converted.info.pop("icc_profile", None)
    return converted


def _prepare(image: Image.Image, size: ThumbSize) -> Image.Image:
    """EXIF-transpose, drop the ICC profile, flatten alpha on mid-grey, shrink to ``size``.

    ``Image.thumbnail()`` only ever shrinks an image to fit the box, so this never upscales.
    """
    transposed = ImageOps.exif_transpose(image)
    prepared = transposed if transposed is not None else image
    prepared = _drop_icc(prepared)
    if _has_alpha(prepared):
        prepared = prepared.convert("RGBA")
        background = Image.new("RGB", prepared.size, _MID_GREY)
        background.paste(prepared, mask=prepared.split()[-1])
        prepared = background
    elif prepared.mode != "RGB":
        prepared = prepared.convert("RGB")
    prepared.thumbnail((int(size), int(size)), Image.Resampling.LANCZOS)
    return prepared


class ThumbCache:
    """A sharded, budgeted JPEG thumbnail cache addressed by content key. Implements ``probe.ThumbSink``."""

    def __init__(self, base: Path | None = None, budget_bytes: int = DEFAULT_BUDGET_BYTES) -> None:
        self._base = Path(base) if base is not None else config_paths.thumbs_dir()
        self._budget_bytes = budget_bytes

    def path_for(self, key: str, size: ThumbSize) -> Path:
        """The on-disk path for ``key`` at ``size``. Pure; validates ``key`` before returning anything."""
        _validate_key(key)
        subdir = "normal" if size == ThumbSize.NORMAL else "large"
        return self._base / subdir / key[:2] / f"{key}.jpg"

    def store(self, image: Image.Image, key: str, cancel: CancelToken) -> str:
        """Save the NORMAL (256px) thumbnail for ``key``. ``'ok'`` or ``'failed'``; never raises for an
        image error (mirrors ``probe_file``'s never-raises contract) — only a malformed ``key`` or
        cancellation does. An existing key is a no-op: the image is never re-decoded or re-written."""
        target = self.path_for(key, ThumbSize.NORMAL)
        cancel.raise_if_cancelled()
        if target.exists():
            return "ok"
        try:
            prepared = _prepare(image, ThumbSize.NORMAL)
            self._write_atomic(prepared, target)
        except Exception:
            _LOG.warning("failed to store thumbnail %s", key, exc_info=True)
            return "failed"
        return "ok"

    def read(self, key: str, size: ThumbSize = ThumbSize.NORMAL) -> bytes | None:
        """The stored bytes for ``key``/``size``, or ``None`` when absent. Touches mtime (the LRU clock)
        at most once a day, so a hot cache is not rewritten on every read."""
        path = self.path_for(key, size)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        self._touch(path)
        return data

    def ensure_large(self, source: Path, key: str) -> bytes | None:
        """Lazily build the 512px thumbnail for ``key`` from the original file at ``source``.

        ``None`` on any failure (missing file, undecodable, write error) — this is a best-effort, on-demand
        upgrade, never part of the scan's cooperative-cancellation path.
        """
        target = self.path_for(key, ThumbSize.LARGE)
        if target.exists():
            self._touch(target)
            return target.read_bytes()
        try:
            with Image.open(source) as opened:
                opened.load()
                prepared = _prepare(opened, ThumbSize.LARGE)
                self._write_atomic(prepared, target)
        except Exception:
            _LOG.warning("failed to build the large thumbnail for %s", key, exc_info=True)
            return None
        return target.read_bytes()

    def usage(self) -> int:
        """Total bytes held by the cache (both sizes)."""
        return sum(size for _mtime, size, _path in self._entries())

    def evict(self) -> int:
        """Delete the oldest-mtime thumbnails until usage is at or under 90% of the budget.

        A no-op under budget. Meant to run once, at scan end (never mid-scan). Returns the bytes freed.
        """
        entries = self._entries()
        total = sum(size for _mtime, size, _path in entries)
        if total <= self._budget_bytes:
            return 0
        target = int(self._budget_bytes * _EVICT_TARGET_FRACTION)
        entries.sort(key=lambda entry: entry[0])  # oldest mtime first
        freed = 0
        for _mtime, size, path in entries:
            if total - freed <= target:
                break
            try:
                path.unlink()
            except OSError:
                continue
            freed += size
        return freed

    def clear(self) -> int:
        """Delete every thumbnail. Returns the bytes freed."""
        total = self.usage()
        if self._base.exists():
            shutil.rmtree(self._base, ignore_errors=True)
        return total

    # ── internals ────────────────────────────────────────────────────────────────────────────────────────

    def _entries(self) -> list[tuple[float, int, Path]]:
        if not self._base.exists():
            return []
        entries: list[tuple[float, int, Path]] = []
        for path in self._base.rglob("*.jpg"):
            try:
                info = path.stat()
            except OSError:
                continue
            entries.append((info.st_mtime, info.st_size, path))
        return entries

    def _touch(self, path: Path) -> None:
        now = time.time()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if now - mtime >= _TOUCH_INTERVAL_SECONDS:
            os.utime(path, (now, now))

    def _write_atomic(self, image: Image.Image, path: Path) -> None:
        self._ensure_private_dir(path.parent)
        tmp = path.with_name(path.name + ".tmp")
        try:
            image.save(tmp, format="JPEG", quality=85)
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _ensure_private_dir(self, path: Path) -> None:
        """``mkdir -p`` with every newly created level ``0700`` (``Path.mkdir(parents=True, mode=...)``
        leaves intermediate directories at the default mode, which is not private enough here)."""
        missing: list[Path] = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
