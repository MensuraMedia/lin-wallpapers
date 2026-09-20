"""Frozen records, 1:1 with the catalogue tables (M1 contract §2.4). Pure data — no SQL, no I/O.

``*_from_row`` build a record from a ``sqlite3.Row`` that selected every column of its table; integer
flags become ``bool``. Nothing here is trusted input for SQL: records travel *out* of the catalogue.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ImageRow:
    id: int
    path: str
    dir: str
    name: str
    root_id: int | None
    volume_id: str | None
    device: int | None
    inode: int | None
    mtime_ns: int | None
    size: int | None
    width: int | None  # after EXIF rotation; NULL when the header could not be read
    height: int | None
    exif_orientation: int | None
    format: str | None
    has_alpha: bool
    is_animated: bool
    has_icc: bool
    aspect: float | None
    megapixels: float | None
    probe_status: str
    probe_error: str | None
    score: int | None  # M2
    badges: str | None  # M2
    palette: str | None  # M2
    dhash: int | None  # M2
    thumb_key: str | None
    thumb_status: str | None
    first_seen: int | None
    last_seen: int | None
    seen_scan: int | None
    missing: bool
    excluded_by: int | None


@dataclass(frozen=True)
class RootRow:
    id: int
    path: str
    kind: str
    enabled: bool
    volume_id: str | None
    last_scan: int | None
    last_scan_id: int | None


@dataclass(frozen=True)
class VolumeRow:
    volume_id: str
    label: str | None
    fstype: str | None
    last_mount: str | None
    removable: bool
    network: bool
    stable_inodes: bool
    scan_answer: str | None
    online: bool
    last_seen: int | None


@dataclass(frozen=True)
class DisplayRow:
    id: int
    name: str
    width: int
    height: int
    scale: float
    is_primary: bool
    source: str
    connected: bool  # True = part of the current target set (detected or declared)
    first_seen: int | None
    last_seen: int | None


@dataclass(frozen=True)
class ScanRow:
    id: int
    started: int
    finished: int | None
    pid: int | None
    root_ids: str | None
    display_set: str | None
    threshold_pct: int | None
    found: int
    probed: int
    unchanged: int
    ideal: int
    skipped: int
    issues: str | None
    reason: str | None
    result: str


@dataclass(frozen=True)
class RuleRow:
    id: int
    kind: str
    value: str
    volume_id: str | None
    device: int | None
    inode: int | None
    root_id: int | None
    group_id: int | None
    builtin: bool
    enabled: bool
    created: int | None
    note: str | None


@dataclass(frozen=True)
class FlagDelta:
    """What ``apply_exclusions`` changed: rows newly flagged, rows whose flag was cleared."""

    flagged: int
    cleared: int


@dataclass(frozen=True)
class RulePreview:
    """ "This rule would exclude ``images`` images in ``folders`` folders" — plus the first few paths."""

    rule_id: int
    images: int
    folders: int
    sample_paths: tuple[str, ...]


@dataclass(frozen=True)
class Page(Generic[T]):
    rows: tuple[T, ...]
    total: int
    offset: int


def image_from_row(row: sqlite3.Row) -> ImageRow:
    return ImageRow(
        id=row["id"],
        path=row["path"],
        dir=row["dir"],
        name=row["name"],
        root_id=row["root_id"],
        volume_id=row["volume_id"],
        device=row["device"],
        inode=row["inode"],
        mtime_ns=row["mtime_ns"],
        size=row["size"],
        width=row["width"],
        height=row["height"],
        exif_orientation=row["exif_orientation"],
        format=row["format"],
        has_alpha=bool(row["has_alpha"]),
        is_animated=bool(row["is_animated"]),
        has_icc=bool(row["has_icc"]),
        aspect=row["aspect"],
        megapixels=row["megapixels"],
        probe_status=row["probe_status"],
        probe_error=row["probe_error"],
        score=row["score"],
        badges=row["badges"],
        palette=row["palette"],
        dhash=row["dhash"],
        thumb_key=row["thumb_key"],
        thumb_status=row["thumb_status"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        seen_scan=row["seen_scan"],
        missing=bool(row["missing"]),
        excluded_by=row["excluded_by"],
    )


def root_from_row(row: sqlite3.Row) -> RootRow:
    return RootRow(
        id=row["id"],
        path=row["path"],
        kind=row["kind"],
        enabled=bool(row["enabled"]),
        volume_id=row["volume_id"],
        last_scan=row["last_scan"],
        last_scan_id=row["last_scan_id"],
    )


def volume_from_row(row: sqlite3.Row) -> VolumeRow:
    return VolumeRow(
        volume_id=row["volume_id"],
        label=row["label"],
        fstype=row["fstype"],
        last_mount=row["last_mount"],
        removable=bool(row["removable"]),
        network=bool(row["network"]),
        stable_inodes=bool(row["stable_inodes"]),
        scan_answer=row["scan_answer"],
        online=bool(row["online"]),
        last_seen=row["last_seen"],
    )


def display_from_row(row: sqlite3.Row) -> DisplayRow:
    return DisplayRow(
        id=row["id"],
        name=row["name"],
        width=row["width"],
        height=row["height"],
        scale=float(row["scale"]),
        is_primary=bool(row["is_primary"]),
        source=row["source"],
        connected=bool(row["connected"]),
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
    )


def scan_from_row(row: sqlite3.Row) -> ScanRow:
    return ScanRow(
        id=row["id"],
        started=row["started"],
        finished=row["finished"],
        pid=row["pid"],
        root_ids=row["root_ids"],
        display_set=row["display_set"],
        threshold_pct=row["threshold_pct"],
        found=row["found"] or 0,
        probed=row["probed"] or 0,
        unchanged=row["unchanged"] or 0,
        ideal=row["ideal"] or 0,
        skipped=row["skipped"] or 0,
        issues=row["issues"],
        reason=row["reason"],
        result=row["result"],
    )


def rule_from_row(row: sqlite3.Row) -> RuleRow:
    return RuleRow(
        id=row["id"],
        kind=row["kind"],
        value=row["value"],
        volume_id=row["volume_id"],
        device=row["device"],
        inode=row["inode"],
        root_id=row["root_id"],
        group_id=row["group_id"],
        builtin=bool(row["builtin"]),
        enabled=bool(row["enabled"]),
        created=row["created"],
        note=row["note"],
    )
