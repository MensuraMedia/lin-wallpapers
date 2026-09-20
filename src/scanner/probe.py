"""Opening a candidate file to find out what it actually is (concept §5, M1.6, contract §2.7).

Phase two of the two-phase scan. Everything here is defensive: a wallpaper folder is user-controlled data,
so a truncated JPEG, a text file wearing a ``.jpg`` extension, a zero-byte file, a header that claims
40000 × 40000 pixels, or a FIFO someone named ``photo.jpg`` must all come back as data, never as an
exception or a hang. :func:`probe_file` therefore never raises.

Order: ``os.open`` with ``O_NONBLOCK`` (a FIFO must not block the scan waiting for a writer that will never
come) → ``fstat`` the *descriptor*, not the path (the walker's ``stat`` and this one can legitimately see a
different file if the path was replaced in between; :attr:`ProbeResult.key` is always the fd's own) → not a
regular file is an error, not a crash → size 0 is :attr:`ProbeStatus.ZERO_BYTE` → ``Image.open`` reads only
the header.

Ruling Q10/Q10a/Q11 (**do not** set ``Image.MAX_IMAGE_PIXELS = None``): above Pillow's own limit
(``2 * MAX_IMAGE_PIXELS``, ≈ 179 MP) Pillow raises ``DecompressionBombError`` *inside* ``Image.open()``,
before ``.size`` can be read — that becomes :attr:`ProbeStatus.TOO_LARGE` with width/height left at their
"NULL" default of 0. Between our own pixel budget and that limit, Pillow only warns (suppressed here as
error-as-data, never left to print); the header dimensions are recorded and, if they exceed the budget the
file is :attr:`ProbeStatus.OVER_BUDGET` with no decode. A 16-bit greyscale PNG opens with Pillow mode
``"I"`` — bit depth is never inferred from the mode string.

Ruling Q16: :meth:`PIL.Image.Image.draft` gives JPEG a reduced-scale decode (it is a no-op for every other
format), so a merely large — not a bomb — photograph is not fully decoded just to end up as a 256 px
thumbnail. Dimensions and every other recorded field come from the header read at ``Image.open()``, before
``draft()`` can touch them.

Pillow identifies a file by its magic bytes, not its extension: a corrupt file can still reach a *foreign*
plugin whose own ``_open()``/``load()`` raises something Pillow's internal format-dispatch loop does not
catch (only ``SyntaxError``/``IndexError``/``TypeError``/``struct.error`` are caught between plugins —
``ValueError``, ``UnicodeDecodeError`` and others escape ``Image.open()`` outright). Both the open and the
load step therefore end in a blanket ``except Exception``, not just ``except OSError``, so this can never
turn into an unhandled exception in a probe worker (D12: the seconds budget is likewise cooperative, never
a reason to fail an otherwise-valid decode — only the optional thumbnail is skipped once it is spent).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
import time
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from PIL import Image

from src.scanner.walker import Candidate, FileKey
from src.util.cancel import CancelToken

__all__ = [
    "DecodeBudget",
    "ProbeResult",
    "ProbeStatus",
    "ThumbSink",
    "content_key",
    "probe_file",
    "supported_formats",
]

_HEAD_BYTES = 256 * 1024
_TAIL_BYTES = 64 * 1024
_THUMB_DRAFT = (256, 256)  # matches catalogue.thumbs.ThumbSize.NORMAL; this module may not import it
_EXIF_ORIENTATION_TAG = 0x0112

# Known container formats, by extension. Drives `UNSUPPORTED` (a format Pillow cannot even identify but the
# extension names) and `supported_formats()` (which of them this Pillow build can actually open).
_EXTENSION_FORMATS: Mapping[str, str] = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "jpe": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "gif": "GIF",
    "bmp": "BMP",
    "tif": "TIFF",
    "tiff": "TIFF",
    "avif": "AVIF",
    "heif": "HEIF",
    "heic": "HEIF",
    "jxl": "JXL",
    "jp2": "JPEG2000",
    "j2k": "JPEG2000",
}


class ProbeStatus(StrEnum):
    OK = "ok"
    TRUNCATED = "truncated"
    ZERO_BYTE = "zero_byte"
    UNSUPPORTED = "unsupported"
    OVER_BUDGET = "over_budget"
    TOO_LARGE = "too_large"  # ruling Q11
    ERROR = "error"


@dataclass(frozen=True)
class DecodeBudget:
    max_pixels: int = 100_000_000
    max_jpeg_pixels: int = 400_000_000  # JPEG decodes cheaply at any nominal size via draft()
    max_seconds: float = 5.0


@dataclass(frozen=True)
class ProbeResult:
    candidate: Candidate
    key: FileKey  # re-read with fstat on the opened fd — the walker's own stat may now be stale
    status: ProbeStatus
    error: str = ""
    width: int = 0
    height: int = 0
    exif_orientation: int = 1
    format: str = ""
    has_alpha: bool = False
    is_animated: bool = False
    has_icc: bool = False
    thumb_key: str | None = None
    thumb_status: str | None = None
    seconds: float = 0.0


class ThumbSink(Protocol):
    def store(self, image: Image.Image, key: str, cancel: CancelToken) -> str: ...  # -> 'ok' | 'failed'


def supported_formats() -> dict[str, bool]:
    """Which of the known container formats this Pillow build can actually open, by plugin registration.

    Drives ``LOADER_MISSING`` upstream (D1): on a Pillow 10.2 without AVIF/HEIF/JXL plugins these come back
    ``False`` — the format is known, just not decodable here, which is a different story than a corrupt
    file. Never raises; ``Image.init()`` is idempotent.
    """
    Image.init()
    names = sorted(set(_EXTENSION_FORMATS.values()))
    return {name: name in Image.OPEN for name in names}


def content_key(fd: int, size: int) -> str:
    """blake2b-128 hex of ``size`` ‖ the first 256 KiB ‖ the last 64 KiB, by positional read.

    ``pread`` never moves the descriptor's file offset, so this can run before, after, or (harmlessly)
    interleaved with the sequential reads ``Image.open``/``load`` make on the same fd.
    """
    head = os.pread(fd, min(size, _HEAD_BYTES), 0) if size else b""
    tail_len = min(size, _TAIL_BYTES)
    tail = os.pread(fd, tail_len, size - tail_len) if tail_len else b""
    digest = hashlib.blake2b(digest_size=16)
    digest.update(size.to_bytes(8, "big"))
    digest.update(head)
    digest.update(tail)
    return digest.hexdigest()


def _detail(exc: BaseException) -> str:
    return getattr(exc, "strerror", None) or str(exc) or type(exc).__name__


def _format_for_extension(path: str) -> str | None:
    dot = path.rfind(".")
    if dot <= 0 or dot == len(path) - 1:
        return None
    return _EXTENSION_FORMATS.get(path[dot + 1 :].lower())


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info


def _is_animated(image: Image.Image) -> bool:
    animated = getattr(image, "is_animated", None)
    if animated is not None:
        return bool(animated)
    try:
        return int(getattr(image, "n_frames", 1)) > 1
    except Exception:
        return False


def _exif_orientation(image: Image.Image) -> int:
    try:
        value = image.getexif().get(_EXIF_ORIENTATION_TAG, 1)
    except Exception:
        return 1
    return int(value) if isinstance(value, int) and 1 <= value <= 8 else 1


def _open_failed(c: Candidate, key: FileKey, exc: BaseException | None = None) -> ProbeResult:
    """``Image.open()`` could not make sense of the file: a known-but-unsupported format by extension, or
    corrupt/foreign data reported with whatever detail Pillow gave (``exc``, when there is one)."""
    fmt = _format_for_extension(c.path)
    if fmt is not None and not supported_formats().get(fmt, True):
        return ProbeResult(c, key, ProbeStatus.UNSUPPORTED, format=fmt)
    error = _detail(exc) if exc is not None else "cannot identify image file"
    return ProbeResult(c, key, ProbeStatus.ERROR, error=error)


def probe_file(
    c: Candidate, budget: DecodeBudget, thumbs: ThumbSink | None, cancel: CancelToken
) -> ProbeResult:
    """Probe one candidate. Never raises: every failure becomes a :class:`ProbeResult` with a status."""
    started = time.monotonic()
    try:
        fd = os.open(c.path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        return ProbeResult(c, c.key, ProbeStatus.ERROR, error=_detail(exc))
    try:
        return _probe(c, fd, budget, thumbs, cancel, started)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


def _probe(
    c: Candidate, fd: int, budget: DecodeBudget, thumbs: ThumbSink | None, cancel: CancelToken, started: float
) -> ProbeResult:
    try:
        st = os.fstat(fd)
    except OSError as exc:
        return ProbeResult(c, c.key, ProbeStatus.ERROR, error=_detail(exc))
    if not stat.S_ISREG(st.st_mode):
        return ProbeResult(c, c.key, ProbeStatus.ERROR, error="not a regular file")
    key: FileKey = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
    if st.st_size == 0:
        return ProbeResult(c, key, ProbeStatus.ZERO_BYTE)

    reader = os.fdopen(fd, "rb", closefd=False)  # this function's caller owns closing `fd`
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            try:
                image = Image.open(reader)
            except Image.DecompressionBombError:
                return ProbeResult(c, key, ProbeStatus.TOO_LARGE)
            except Image.UnidentifiedImageError as exc:
                return _open_failed(c, key, exc)
            except Exception as exc:
                # A hostile file can trip a *foreign* plugin: Pillow's own dispatcher
                # (PIL.Image._open_core) only catches SyntaxError/IndexError/TypeError/struct.error while
                # trying each registered format in turn — a plugin whose accept() matched the magic bytes
                # but whose _open() then hits a ValueError/UnicodeDecodeError/etc. (e.g. corrupt SGI/IM/PPM
                # content) raises straight out of Image.open(). probe_file must not propagate it either way.
                return _open_failed(c, key, exc)

            width, height = image.size
            fmt = image.format or _format_for_extension(c.path) or ""
            exif_orientation = _exif_orientation(image)
            has_alpha = _has_alpha(image)
            is_animated = _is_animated(image)
            has_icc = "icc_profile" in image.info

            def _result(
                status: ProbeStatus,
                *,
                error: str = "",
                thumb_key: str | None = None,
                thumb_status: str | None = None,
            ) -> ProbeResult:
                return ProbeResult(
                    c,
                    key,
                    status,
                    error=error,
                    width=width,
                    height=height,
                    exif_orientation=exif_orientation,
                    format=fmt,
                    has_alpha=has_alpha,
                    is_animated=is_animated,
                    has_icc=has_icc,
                    thumb_key=thumb_key,
                    thumb_status=thumb_status,
                    seconds=time.monotonic() - started,
                )

            limit = budget.max_jpeg_pixels if fmt == "JPEG" else budget.max_pixels
            if width * height > limit:
                return _result(ProbeStatus.OVER_BUDGET)

            # D12: the seconds budget is cooperative, not a hard guard (the pixel/byte caps are) — a
            # thread cannot be killed mid-decode, and a header read that was merely *slow* (thread
            # contention, a loaded disk) must never turn an otherwise-valid image into a spurious ERROR.
            # `load()` itself is therefore never skipped on time alone; only the optional thumbnail below
            # — extra, avoidable work — is skipped once the budget is already spent.
            if fmt == "JPEG":
                image.draft("RGB", _THUMB_DRAFT)
            try:
                image.load()
            except Exception as exc:  # any format-specific decode failure, not just OSError (see above)
                return _result(ProbeStatus.TRUNCATED, error=_detail(exc))

            thumb_key: str | None = None
            thumb_status: str | None = None
            within_time_budget = time.monotonic() - started <= budget.max_seconds
            if thumbs is not None and not cancel.cancelled and within_time_budget:
                thumb_key = content_key(fd, st.st_size)
                try:
                    thumb_status = thumbs.store(image, thumb_key, cancel)
                except Exception:  # ThumbSink is an external implementation; never let it escape probe_file
                    thumb_status = "failed"

            return _result(ProbeStatus.OK, thumb_key=thumb_key, thumb_status=thumb_status)
    finally:
        reader.close()
