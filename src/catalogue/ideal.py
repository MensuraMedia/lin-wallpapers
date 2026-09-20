"""The ideal-images segment (concept §6.1, M1.5a): which images fit which display, on dimensions alone.

``evaluate`` and ``explain`` are pure. ``rebuild`` is one ``INSERT … SELECT`` over ``image × display`` that
reads stored dimensions only — this module has no file access at all, so a monitor change never opens an
image. Every decision uses INTEGER arithmetic (D3), identically in Python and in SQL, so the two cannot
disagree at a boundary; the REAL ``crop_loss`` / ``coverage`` values are for display only.

With ``w × h`` the image (after EXIF rotation) and ``W × H`` the display: ``a = w·H``, ``b = W·h``. Fill mode
scales by ``max(W/w, H/h)`` and centre-crops; the kept share of the image area is ``min(a,b)/max(a,b)``.

* COVERS       ``w ≥ W and h ≥ H`` (no upscaling, ever)
* CROP(t)      ``100·min(a,b) ≥ (100−t)·max(a,b)``
* ORIENTATION  fails iff one is landscape and the other portrait (square matches either)
* INTEGRITY    decodable, still, opaque, and sane positive dimensions
* IDEAL        all four.  NEAR (rulings Q2): not ideal, INTEGRITY and ORIENTATION hold, and what failed
  failed narrowly — ``10·w ≥ 9·W and 10·h ≥ 9·H`` (linear coverage ≥ 90 % on both axes) and CROP(25).

Excluded and missing images are NOT part of the verdict: they are filtered when the segment is queried
(D7), so toggling an exclusion needs no rebuild. Pins (``ideal_pin``) are never touched by a rebuild.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from src.catalogue.db import CatalogueError, transaction
from src.scanner.displays import Display

DEFAULT_THRESHOLD_PCT = 16  # ruling Q1
MAX_THRESHOLD_PCT = 40
NEAR_CROP_PCT = 25
NEAR_COVER_PCT = 90
MAX_DIMENSION = 1_000_000  # keeps 100·w·H far inside SQLite's signed 64-bit integers


class Verdict(StrEnum):
    IDEAL = "ideal"
    NEAR = "near"
    NO = "no"


class Test(StrEnum):
    __test__ = False  # not a pytest class, whatever the name says

    COVERS = "covers"
    CROP = "crop"
    ORIENTATION = "orientation"
    INTEGRITY = "integrity"


@dataclass(frozen=True)
class ImageDims:
    width: int
    height: int
    has_alpha: bool = False
    is_animated: bool = False
    decodable: bool = True


@dataclass(frozen=True)
class IdealVerdict:
    verdict: Verdict
    exact: bool
    crop_loss: float  # display only
    coverage: float  # display only; 1 − coverage = "N % too small"
    failed: tuple[Test, ...]


def check_threshold(threshold_pct: int) -> int:
    if type(threshold_pct) is not int or not 0 <= threshold_pct <= MAX_THRESHOLD_PCT:
        raise ValueError(f"threshold_pct must be an integer in 0..{MAX_THRESHOLD_PCT}, got {threshold_pct!r}")
    return threshold_pct


def _sane(value: object) -> bool:
    return type(value) is int and 0 < value <= MAX_DIMENSION


def evaluate(image: ImageDims, display: Display, threshold_pct: int = DEFAULT_THRESHOLD_PCT) -> IdealVerdict:
    """Judge one image against one display. Bad image data is a verdict (``NO``), never an exception;
    a bad threshold or display is a programming error (``ValueError``)."""
    check_threshold(threshold_pct)
    big_w, big_h = display.width, display.height
    if not (_sane(big_w) and _sane(big_h)):
        raise ValueError(f"display dimensions out of range: {big_w!r} x {big_h!r}")
    w, h = image.width, image.height
    if not (_sane(w) and _sane(h)):
        return IdealVerdict(Verdict.NO, False, 0.0, 0.0, (Test.INTEGRITY,))

    a, b = w * big_h, big_w * h
    low, high = min(a, b), max(a, b)
    covers = w >= big_w and h >= big_h
    crop_ok = 100 * low >= (100 - threshold_pct) * high
    orientation_ok = not ((w > h and big_w < big_h) or (w < h and big_w > big_h))
    integrity_ok = image.decodable and not image.is_animated and not image.has_alpha
    near_cover = 100 * w >= NEAR_COVER_PCT * big_w and 100 * h >= NEAR_COVER_PCT * big_h
    near_crop = 100 * low >= (100 - NEAR_CROP_PCT) * high

    failed = tuple(
        test
        for test, passed in (
            (Test.COVERS, covers),
            (Test.CROP, crop_ok),
            (Test.ORIENTATION, orientation_ok),
            (Test.INTEGRITY, integrity_ok),
        )
        if not passed
    )
    if not failed:
        verdict = Verdict.IDEAL
    elif integrity_ok and orientation_ok and near_cover and near_crop:
        verdict = Verdict.NEAR
    else:
        verdict = Verdict.NO
    return IdealVerdict(
        verdict=verdict,
        exact=(w == big_w and h == big_h),
        crop_loss=1.0 - low / high,
        coverage=min(1.0, w / big_w, h / big_h),
        failed=failed,
    )


def _percent(fraction: float) -> str:
    text = f"{100.0 * fraction:.1f}"
    return text.removesuffix(".0")


def _shape(width: int, height: int) -> str:
    return "landscape" if width > height else "portrait" if width < height else "square"


def explain(image: ImageDims, display: Display, v: IdealVerdict) -> str:
    """One sentence for a member ("3840 × 2160 covers 1920 × 1080; fill crop loses 0 %") or for what kept
    an image out ("1760 × 990 — 8 % too small for eDP-1"). The GUI and the CLI both print this string."""
    size = f"{image.width} × {image.height}"
    target = f"{display.width} × {display.height}"
    if v.verdict is Verdict.IDEAL:
        if v.exact:
            return f"{size} matches {display.name} exactly"
        return f"{size} covers {target}; fill crop loses {_percent(v.crop_loss)} %"
    parts: list[str] = []
    if Test.INTEGRITY in v.failed:
        if not _sane(image.width) or not _sane(image.height):
            return "dimensions unknown — the file could not be read"
        if not image.decodable:
            parts.append("could not be decoded")
        if image.is_animated:
            parts.append("is animated")
        if image.has_alpha:
            parts.append("has an alpha channel")
    if Test.ORIENTATION in v.failed:
        parts.append(
            f"is {_shape(image.width, image.height)} but {display.name} is "
            f"{_shape(display.width, display.height)}"
        )
    if Test.COVERS in v.failed:
        short = max(1, round(100.0 * (1.0 - v.coverage)))
        parts.append(f"{short} % too small for {display.name}")
    if Test.CROP in v.failed:
        parts.append(f"fill crop on {display.name} loses {_percent(v.crop_loss)} % of the picture")
    return f"{size} — " + "; ".join(parts)


# ── SQL side ─────────────────────────────────────────────────────────────────────────────────────────────

_DELETE_ALL = "DELETE FROM ideal_image"
_DELETE_SOME = "DELETE FROM ideal_image WHERE image_id IN (SELECT value FROM json_each(:ids))"

# The last clause matters above a 25 % threshold: an image that covers the screen and passes CROP(t) is
# ideal even when it fails the near-miss bound CROP(25) (found by the Python ≡ SQL property test).
_INSERT = """
INSERT INTO ideal_image(image_id, display_id, verdict, exact, crop_loss, coverage)
SELECT i.id, d.id,
  CASE WHEN i.width >= d.width AND i.height >= d.height
        AND 100 * min(i.width * d.height, d.width * i.height)
            >= (100 - :t) * max(i.width * d.height, d.width * i.height)
       THEN 'ideal' ELSE 'near' END,
  i.width = d.width AND i.height = d.height,
  1.0 - CAST(min(i.width * d.height, d.width * i.height) AS REAL)
        / max(i.width * d.height, d.width * i.height),
  min(1.0, CAST(i.width AS REAL) / d.width, CAST(i.height AS REAL) / d.height)
FROM image i CROSS JOIN display d
WHERE d.connected = 1
  AND i.probe_status = 'ok' AND i.has_alpha = 0 AND i.is_animated = 0
  AND typeof(i.width) = 'integer' AND typeof(i.height) = 'integer'
  AND i.width > 0 AND i.height > 0 AND i.width <= :max_dim AND i.height <= :max_dim
  AND NOT ((i.width > i.height AND d.width < d.height) OR (i.width < i.height AND d.width > d.height))
  AND 100 * i.width >= :near_cover * d.width AND 100 * i.height >= :near_cover * d.height
  AND (100 * min(i.width * d.height, d.width * i.height)
         >= (100 - :near_crop) * max(i.width * d.height, d.width * i.height)
       OR (i.width >= d.width AND i.height >= d.height
           AND 100 * min(i.width * d.height, d.width * i.height)
               >= (100 - :t) * max(i.width * d.height, d.width * i.height)))
"""
_INSERT_SOME = _INSERT + "  AND i.id IN (SELECT value FROM json_each(:ids))\n"


def rebuild(conn: sqlite3.Connection, threshold_pct: int, image_ids: Sequence[int] | None = None) -> int:
    """Recompute ``ideal_image`` for every image, or for ``image_ids`` only (the scan's incremental path).

    Judges against the current target displays (``display.connected = 1``). Returns the number of rows
    written (ideal + near). Atomic: joins the caller's transaction or opens its own. Pins are untouched.
    """
    params: dict[str, object] = {
        "t": check_threshold(threshold_pct),
        "max_dim": MAX_DIMENSION,
        "near_cover": NEAR_COVER_PCT,
        "near_crop": NEAR_CROP_PCT,
    }
    with transaction(conn):
        if image_ids is None:
            conn.execute(_DELETE_ALL)
            return int(conn.execute(_INSERT, params).rowcount)
        ids = json.dumps([int(image_id) for image_id in image_ids])
        conn.execute(_DELETE_SOME, {"ids": ids})
        return int(conn.execute(_INSERT_SOME, {**params, "ids": ids}).rowcount)


def set_pin(conn: sqlite3.Connection, image_id: int, pinned: Literal["in", "out"] | None) -> None:
    """*Add to ideal anyway* (``"in"``), *Remove from ideal* (``"out"``), or drop the pin (``None``)."""
    if pinned not in ("in", "out", None):
        raise ValueError(f"pinned must be 'in', 'out' or None, got {pinned!r}")
    with transaction(conn):
        if pinned is None:
            conn.execute("DELETE FROM ideal_pin WHERE image_id = ?", (image_id,))
            return
        if conn.execute("SELECT 1 FROM image WHERE id = ?", (image_id,)).fetchone() is None:
            raise CatalogueError(f"no image with id {image_id}")
        conn.execute(
            "INSERT INTO ideal_pin(image_id, pinned) VALUES (?, ?) "
            "ON CONFLICT(image_id) DO UPDATE SET pinned = excluded.pinned",
            (image_id, pinned),
        )


def get_pin(conn: sqlite3.Connection, image_id: int) -> Literal["in", "out"] | None:
    row = conn.execute("SELECT pinned FROM ideal_pin WHERE image_id = ?", (image_id,)).fetchone()
    if row is None:
        return None
    return "in" if row[0] == "in" else "out"
