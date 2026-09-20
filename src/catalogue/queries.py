"""The query builder behind Browse, the segments and ``linwp list`` (M1 contract §2.5). Parameterised only.

Security rules of this module (tests enforce them, including an AST check):

* every VALUE is a ``?`` parameter — search text, filter values, limits, display ids, all of them;
* SQL TEXT is assembled only from the module-level constant fragments below, chosen by enum — ``ORDER BY``
  comes from a ``dict[Sort, str]``, never from a caller's string; an unknown sort key is refused;
* there is no f-string, ``%`` formatting or ``.format`` anywhere in this file;
* ``LIKE`` patterns escape ``%``, ``_`` and the escape character itself.

Segments (concept §6.1, rulings Q2/Q3). *Ideal for this desktop* = ideal for ANY target display, plus pins
``in``, minus pins ``out``; *every display*, *per display*, *exact match* and *larger than needed* narrow it;
*near misses* sit outside it. Excluded and missing images are filtered here, at query time (D7).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from enum import StrEnum

from src.catalogue import ideal
from src.catalogue.db import DEFAULT_SETTINGS, get_setting
from src.catalogue.model import DisplayRow, ImageRow, Page, display_from_row, image_from_row
from src.scanner.displays import Display, DisplaySource

MAX_LIMIT = 1000
MAX_SEARCH_TERMS = 8
MAX_TERM_CHARS = 256
ASPECT_TOLERANCE = 0.03


class Segment(StrEnum):
    ALL = "all"
    IDEAL = "ideal"
    NEAR_MISS = "near_miss"


class Sort(StrEnum):
    NAME = "name"
    DATE_ADDED = "date_added"
    SIZE = "size"
    RESOLUTION = "resolution"


class Orientation(StrEnum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


class AspectBucket(StrEnum):
    R16_9 = "16:9"
    R16_10 = "16:10"
    R3_2 = "3:2"
    R4_3 = "4:3"
    R21_9 = "21:9"
    R1_1 = "1:1"
    OTHER = "other"


class UnsupportedSort(ValueError):
    """The sort key is not one this release can order by (``score`` arrives in M2)."""


@dataclass(frozen=True)
class QuerySpec:
    segment: Segment = Segment.ALL
    display_id: int | None = None
    every_display: bool = False
    exact: bool | None = None  # True = exact match, False = larger than needed
    search: str = ""
    min_width: int | None = None
    min_height: int | None = None
    min_long_edge: int | None = None  # the default view filter of ruling Q7 — see default_spec()
    aspect: AspectBucket | None = None
    orientation: Orientation | None = None
    formats: tuple[str, ...] = ()
    root_id: int | None = None
    dir_prefix: str | None = None
    missing: bool | None = None  # None = both (missing rows are dimmed, not hidden); True/False = only/none
    include_excluded: bool = False
    include_unusable: bool = False  # probe_status != 'ok'
    sort: Sort = Sort.NAME
    descending: bool = False
    limit: int = 200
    offset: int = 0


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: tuple[object, ...]


# ── constant SQL fragments ───────────────────────────────────────────────────────────────────────────────

_SELECT_ROWS = "SELECT i.* FROM image i LEFT JOIN ideal_pin p ON p.image_id = i.id"
_SELECT_COUNT = "SELECT count(*) FROM image i LEFT JOIN ideal_pin p ON p.image_id = i.id"

_ORDER_ASC: dict[Sort, str] = {
    Sort.NAME: " ORDER BY i.name COLLATE NOCASE ASC, i.id ASC",
    Sort.DATE_ADDED: " ORDER BY i.first_seen ASC, i.id ASC",
    Sort.SIZE: " ORDER BY i.size ASC, i.id ASC",
    Sort.RESOLUTION: " ORDER BY i.width * i.height ASC, i.id ASC",
}
_ORDER_DESC: dict[Sort, str] = {
    Sort.NAME: " ORDER BY i.name COLLATE NOCASE DESC, i.id DESC",
    Sort.DATE_ADDED: " ORDER BY i.first_seen DESC, i.id DESC",
    Sort.SIZE: " ORDER BY i.size DESC, i.id DESC",
    Sort.RESOLUTION: " ORDER BY i.width * i.height DESC, i.id DESC",
}
_LIMIT = " LIMIT ? OFFSET ?"

_NOT_EXCLUDED = "i.excluded_by IS NULL"
_USABLE = "i.probe_status = 'ok'"
_MISSING_IS = "i.missing = ?"
_PRESENT = "i.missing = 0"
_SEARCH = "(i.name LIKE ? ESCAPE '\\' OR i.dir LIKE ? ESCAPE '\\')"
_MIN_WIDTH = "i.width >= ?"
_MIN_HEIGHT = "i.height >= ?"
_MIN_LONG_EDGE = "(i.probe_status <> 'ok' OR max(i.width, i.height) >= ?)"
_FORMATS = "upper(i.format) IN (SELECT value FROM json_each(?))"
_ROOT = "i.root_id = ?"
_DIR_PREFIX = "(i.dir = ? OR (i.dir >= ? AND i.dir < ?))"  # binary range: case-sensitive, uses image_dir

_ORIENTATION: dict[Orientation, str] = {
    Orientation.LANDSCAPE: "i.width > i.height",
    Orientation.PORTRAIT: "i.width < i.height",
    Orientation.SQUARE: "i.width = i.height",
}
_ASPECT_TARGETS: dict[AspectBucket, float] = {
    AspectBucket.R16_9: 16 / 9,
    AspectBucket.R16_10: 16 / 10,
    AspectBucket.R3_2: 3 / 2,
    AspectBucket.R4_3: 4 / 3,
    AspectBucket.R21_9: 21 / 9,
    AspectBucket.R1_1: 1.0,
}
_ASPECT_IS = "(i.height > 0 AND abs(CAST(i.width AS REAL) / i.height - ?) <= ?)"
_ASPECT_OTHER = (
    "(i.height > 0" + " AND abs(CAST(i.width AS REAL) / i.height - ?) > ?" * len(_ASPECT_TARGETS) + ")"
)

_NOT_PINNED_OUT = "ifnull(p.pinned, '') <> 'out'"
_NOT_PINNED_IN = "ifnull(p.pinned, '') <> 'in'"
_PINNED_IN_OR = "(p.pinned = 'in' OR "
_VERDICT_HEAD = (
    "EXISTS (SELECT 1 FROM ideal_image x JOIN display d ON d.id = x.display_id"
    " WHERE x.image_id = i.id AND d.connected = 1 AND x.verdict = ?"
)
_NO_IDEAL_VERDICT = (
    "NOT EXISTS (SELECT 1 FROM ideal_image x JOIN display d ON d.id = x.display_id"
    " WHERE x.image_id = i.id AND d.connected = 1 AND x.verdict = 'ideal')"
)
_AND_DISPLAY = " AND x.display_id = ?"
_AND_EXACT = " AND x.exact = ?"
_EVERY_HEAD = (
    "(EXISTS (SELECT 1 FROM display WHERE connected = 1) AND (SELECT count(*) FROM ideal_image x"
    " JOIN display d ON d.id = x.display_id"
    " WHERE x.image_id = i.id AND d.connected = 1 AND x.verdict = 'ideal'"
)
_EVERY_TAIL = ") = (SELECT count(*) FROM display WHERE connected = 1))"

_IMAGE_BY_ID = "SELECT * FROM image WHERE id = ?"
_IMAGE_BY_PATH = "SELECT * FROM image WHERE path = ?"
_TARGET_DISPLAYS = "SELECT * FROM display WHERE connected = 1 ORDER BY is_primary DESC, id ASC"


# ── validation (defence in depth: values are bound anyway) ───────────────────────────────────────────────


def _int(name: str, value: object) -> int:
    if type(value) is not int:
        raise TypeError("QuerySpec." + name + " must be an int")
    return value


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("QuerySpec." + name + " must be a str")
    # SQLite TEXT cannot hold lone surrogates (a surrogate-escaped argv): such text can match nothing stored
    if value.isascii():
        return value
    return "".join("\ufffd" if "\ud800" <= ch <= "\udfff" else ch for ch in value)


def like_escape(text: str) -> str:
    """Escape ``\\``, ``%`` and ``_`` for ``LIKE ? ESCAPE '\\'``."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _order(spec: QuerySpec) -> str:
    try:
        key = Sort(spec.sort)
    except ValueError:
        raise UnsupportedSort("unsupported sort key: " + repr(spec.sort)) from None
    return (_ORDER_DESC if spec.descending else _ORDER_ASC)[key]


def _segment(spec: QuerySpec, where: list[str], params: list[object]) -> bool:
    """Append the segment's clauses. Returns True when the segment forces present, non-excluded rows."""
    segment = Segment(spec.segment)
    if segment is Segment.ALL:
        return False
    display_id = None if spec.display_id is None else _int("display_id", spec.display_id)
    if segment is Segment.NEAR_MISS:
        clause = _VERDICT_HEAD
        params.append(ideal.Verdict.NEAR.value)
        if display_id is not None:
            clause += _AND_DISPLAY
            params.append(display_id)
        else:
            where.append(_NO_IDEAL_VERDICT)
        where.append(clause + ")")
        where.append(_NOT_PINNED_IN)
        return True
    # Segment.IDEAL
    if spec.every_display:
        fact = _EVERY_HEAD
        if spec.exact is not None:
            fact += _AND_EXACT
            params.append(int(bool(spec.exact)))
        fact += _EVERY_TAIL
    else:
        fact = _VERDICT_HEAD
        params.append(ideal.Verdict.IDEAL.value)
        if display_id is not None:
            fact += _AND_DISPLAY
            params.append(display_id)
        if spec.exact is not None:
            fact += _AND_EXACT
            params.append(int(bool(spec.exact)))
        fact += ")"
    # A pin "in" is a manual member of the segment, not a fact about pixels: it never counts as an
    # exact match or as larger than needed.
    where.append(fact if spec.exact is not None else _PINNED_IN_OR + fact + ")")
    where.append(_NOT_PINNED_OUT)
    return True


def _where(spec: QuerySpec) -> tuple[str, list[object]]:
    where: list[str] = []
    params: list[object] = []
    forced = _segment(spec, where, params)

    if forced or not spec.include_excluded:
        where.append(_NOT_EXCLUDED)
    if forced:
        where.append(_PRESENT)
    elif spec.missing is not None:
        where.append(_MISSING_IS)
        params.append(int(bool(spec.missing)))
    if not spec.include_unusable:
        where.append(_USABLE)

    terms = _text("search", spec.search).split()[:MAX_SEARCH_TERMS]
    for term in terms:
        pattern = "%" + like_escape(term[:MAX_TERM_CHARS]) + "%"
        where.append(_SEARCH)
        params += [pattern, pattern]
    if spec.min_width is not None:
        where.append(_MIN_WIDTH)
        params.append(_int("min_width", spec.min_width))
    if spec.min_height is not None:
        where.append(_MIN_HEIGHT)
        params.append(_int("min_height", spec.min_height))
    if spec.min_long_edge is not None:
        where.append(_MIN_LONG_EDGE)
        params.append(_int("min_long_edge", spec.min_long_edge))
    if spec.aspect is not None:
        bucket = AspectBucket(spec.aspect)
        if bucket is AspectBucket.OTHER:
            where.append(_ASPECT_OTHER)
            for target in _ASPECT_TARGETS.values():
                params += [target, ASPECT_TOLERANCE]
        else:
            where.append(_ASPECT_IS)
            params += [_ASPECT_TARGETS[bucket], ASPECT_TOLERANCE]
    if spec.orientation is not None:
        where.append(_ORIENTATION[Orientation(spec.orientation)])
    if spec.formats:
        where.append(_FORMATS)
        params.append(json.dumps([_text("formats", name).upper() for name in spec.formats]))
    if spec.root_id is not None:
        where.append(_ROOT)
        params.append(_int("root_id", spec.root_id))
    if spec.dir_prefix is not None:
        prefix = _text("dir_prefix", spec.dir_prefix).rstrip("/")
        where.append(_DIR_PREFIX)
        params += [prefix or "/", prefix + "/", prefix + "0"]  # "0" is the code point after "/"

    return (" WHERE " + " AND ".join(where)) if where else "", params


def build(spec: QuerySpec) -> CompiledQuery:
    """The page query: filters, a stable order (ties broken by id), ``LIMIT`` clamped to 1..1000."""
    order = _order(spec)
    where, params = _where(spec)
    limit = min(MAX_LIMIT, max(1, _int("limit", spec.limit)))
    offset = max(0, _int("offset", spec.offset))
    return CompiledQuery(_SELECT_ROWS + where + order + _LIMIT, (*params, limit, offset))


def build_count(spec: QuerySpec) -> CompiledQuery:
    _order(spec)  # a bad sort key is refused here too
    where, params = _where(spec)
    return CompiledQuery(_SELECT_COUNT + where, tuple(params))


def fetch_page(conn: sqlite3.Connection, spec: QuerySpec) -> Page[ImageRow]:
    page = build(spec)
    count = build_count(spec)
    rows = tuple(image_from_row(row) for row in conn.execute(page.sql, page.params))
    total = int(conn.execute(count.sql, count.params).fetchone()[0])
    return Page(rows=rows, total=total, offset=max(0, spec.offset))


def default_spec(conn: sqlite3.Connection) -> QuerySpec:
    """The default view: small images are stored but hidden by the ``scan.min_long_edge`` filter (ruling
    Q7). It is an ordinary ``QuerySpec`` field, so the UI shows it as a chip and the user can remove it."""
    fallback = DEFAULT_SETTINGS["scan.min_long_edge"]
    edge = get_setting(conn, "scan.min_long_edge", fallback if isinstance(fallback, int) else 0)
    return QuerySpec(min_long_edge=edge if edge > 0 else None)


def get_image(conn: sqlite3.Connection, id_or_path: int | str) -> ImageRow | None:
    if isinstance(id_or_path, str):
        try:
            id_or_path.encode("utf-8")
        except UnicodeEncodeError:  # no stored path can contain a lone surrogate (D15)
            return None
        row = conn.execute(_IMAGE_BY_PATH, (id_or_path,)).fetchone()
    else:
        row = conn.execute(_IMAGE_BY_ID, (_int("id", id_or_path),)).fetchone()
    return None if row is None else image_from_row(row)


def target_displays(conn: sqlite3.Connection) -> list[DisplayRow]:
    """The displays images are judged against: primary first, then by id."""
    return [display_from_row(row) for row in conn.execute(_TARGET_DISPLAYS)]


def dims_of(image: ImageRow) -> ideal.ImageDims:
    """What ``ideal.evaluate`` needs from a row; unknown dimensions become 0 × 0 (never ideal)."""
    return ideal.ImageDims(
        width=image.width if isinstance(image.width, int) else 0,
        height=image.height if isinstance(image.height, int) else 0,
        has_alpha=image.has_alpha,
        is_animated=image.is_animated,
        decodable=image.probe_status == "ok",
    )


def as_display(row: DisplayRow) -> Display:
    try:
        source = DisplaySource(row.source)
    except ValueError:
        source = DisplaySource.DECLARED
    return Display(
        name=row.name or "display-" + str(row.id),
        width=row.width,
        height=row.height,
        scale=row.scale if row.scale > 0 else 1.0,
        primary=row.is_primary,
        source=source,
    )


def verdicts_for(conn: sqlite3.Connection, image_id: int) -> list[tuple[DisplayRow, ideal.IdealVerdict]]:
    """Per target display, the full verdict with the failed tests (``linwp show``).

    Computed by ``ideal.evaluate`` from the stored row and the stored threshold; tests prove ``evaluate``
    identical to the SQL rebuild.
    """
    image = get_image(conn, image_id)
    if image is None:
        return []
    threshold = get_setting(conn, "ideal.threshold_pct", ideal.DEFAULT_THRESHOLD_PCT)
    if not 0 <= threshold <= ideal.MAX_THRESHOLD_PCT:
        threshold = ideal.DEFAULT_THRESHOLD_PCT
    dims = dims_of(image)
    return [(row, ideal.evaluate(dims, as_display(row), threshold)) for row in target_displays(conn)]


def segment_counts(conn: sqlite3.Connection, base: QuerySpec | None = None) -> dict[str, int]:
    """Counts for the segment switch and the Collections page, under the filters of ``base``.

    Keys: ``all``, ``ideal``, ``near``, ``exact``, ``larger``, ``every``, and ``display:<id>`` per target.
    """
    spec = replace(base or QuerySpec(), display_id=None, every_display=False, exact=None)
    variants: dict[str, QuerySpec] = {
        "all": replace(spec, segment=Segment.ALL),
        "ideal": replace(spec, segment=Segment.IDEAL),
        "near": replace(spec, segment=Segment.NEAR_MISS),
        "exact": replace(spec, segment=Segment.IDEAL, exact=True),
        "larger": replace(spec, segment=Segment.IDEAL, exact=False),
        "every": replace(spec, segment=Segment.IDEAL, every_display=True),
    }
    for display in target_displays(conn):
        variants["display:" + str(display.id)] = replace(spec, segment=Segment.IDEAL, display_id=display.id)
    counts: dict[str, int] = {}
    for key, variant in variants.items():
        compiled = build_count(variant)
        counts[key] = int(conn.execute(compiled.sql, compiled.params).fetchone()[0])
    return counts
