"""``BrowseVM`` — the Browse page's state: a filtered, paged window over the catalogue (M1 §2.9, §3, D16).

The view model owns a private ``QuerySpec`` and mutates it through plain, catalogue-free setters (the filter
chips). Each change re-queries on a worker thread and delivers a frozen :class:`BrowseState` of
:class:`ImageCard` DTOs — a page never sees an ``ImageRow`` or a ``QuerySpec``. Thumbnails reach widgets as
**bytes** (or a :class:`ThumbPlaceholder`), never as a path. The segment defaults to *Ideal* once any image
is ideal for a target display, else *All*. Another process's writes are noticed by comparing
``PRAGMA data_version`` when a page is shown; this process's writes arrive on the change feed, coalesced
through the scheduler so a burst of scan batches becomes one refresh.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.catalogue import queries
from src.catalogue.db import (
    Change,
    ChangeKind,
    add_rule,
    apply_exclusions,
    load_rules,
    remove_rule,
)
from src.catalogue.model import ImageRow
from src.catalogue.queries import QuerySpec, default_spec, fetch_page, get_image, segment_counts
from src.catalogue.thumbs import ThumbSize
from src.scanner.exclude import PatternError, RuleKind, compile_matcher, validate_rule
from src.util.threads import Scheduler, run_in_worker
from src.viewmodels.services import AppServices

# ── page-facing enums (mirror the catalogue's by value, so a page never imports a catalogue type) ──────────


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


# ── DTOs ────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImageCard:
    id: int
    name: str
    path: str
    width: int | None
    height: int | None
    aspect: float | None
    format: str | None
    missing: bool
    excluded: bool
    unusable: bool  # probe_status != 'ok'
    has_thumb: bool


@dataclass(frozen=True)
class ThumbPlaceholder:
    """Delivered instead of bytes when no thumbnail can be shown; ``reason`` picks the fallback art."""

    image_id: int
    reason: str  # 'none' | 'failed' | 'missing'


@dataclass(frozen=True)
class SegmentCounts:
    all: int = 0
    ideal: int = 0
    near: int = 0
    exact: int = 0
    larger: int = 0
    every: int = 0
    per_display: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class ExcludeOutcome:
    """The answer to an *Exclude Image / Folder* action: the new rule's id (as an undo token) and the
    label the page shows in the undo toast (the image name for a file, the directory for a folder)."""

    ok: bool
    rule_id: str | None = None  # str(rule id): the token the page hands back to :meth:`undo_exclusion`
    kind: str = ""  # 'file' | 'folder'
    label: str = ""  # the image name (file) or the directory path (folder)
    message: str = ""  # why it was refused, when ``ok`` is False


@dataclass(frozen=True)
class BrowseState:
    cards: tuple[ImageCard, ...] = ()
    total: int = 0
    offset: int = 0
    segment: str = Segment.ALL.value
    search: str = ""
    counts: SegmentCounts = SegmentCounts()
    selection: frozenset[int] = frozenset()
    loading: bool = False


class BrowseVM:
    def __init__(self, services: AppServices, *, coalesce: Scheduler | None = None) -> None:
        self._services = services
        self._scheduler: Scheduler = services.scheduler
        self._home = str(Path.home())
        # How change-feed bursts are collapsed: the app may pass a 100 ms-timeout scheduler; the default
        # collapses everything queued before the next scheduler turn (idle) into a single refresh.
        self._coalesce: Scheduler = coalesce if coalesce is not None else services.scheduler
        self._observers: list[Callable[[BrowseState], None]] = []
        self._spec = QuerySpec()
        self._state = BrowseState()
        self._selection: set[int] = set()
        self._segment_chosen = False
        self._loaded_defaults = False
        self._generation = 0
        self._data_version: int | None = None
        self._refresh_scheduled = False
        self._unsubscribe = services.feed.subscribe(self._on_change)

    # -- observation ------------------------------------------------------------------------------------

    @property
    def state(self) -> BrowseState:
        return self._state

    def add_observer(self, cb: Callable[[BrowseState], None]) -> Callable[[], None]:
        self._observers.append(cb)

        def remove() -> None:
            if cb in self._observers:
                self._observers.remove(cb)

        return remove

    def close(self) -> None:
        """Drop the change-feed subscription so this VM leaves nothing wired to the writer."""
        self._unsubscribe()

    # -- filters (the chips) ----------------------------------------------------------------------------

    def set_segment(self, segment: Segment) -> object:
        self._segment_chosen = True
        return self._update(segment=queries.Segment(segment.value))

    def set_search(self, text: str) -> object:
        return self._update(search=text)

    def set_sort(self, sort: Sort, *, descending: bool = False) -> object:
        return self._update(sort=queries.Sort(sort.value), descending=descending)

    def set_orientation(self, orientation: Orientation | None) -> object:
        value = None if orientation is None else queries.Orientation(orientation.value)
        return self._update(orientation=value)

    def set_aspect(self, aspect: AspectBucket | None) -> object:
        value = None if aspect is None else queries.AspectBucket(aspect.value)
        return self._update(aspect=value)

    def set_min_long_edge(self, edge: int | None) -> object:
        return self._update(min_long_edge=edge)

    def set_min_size(self, *, width: int | None = None, height: int | None = None) -> object:
        return self._update(min_width=width, min_height=height)

    def set_formats(self, formats: Sequence[str]) -> object:
        return self._update(formats=tuple(formats))

    def set_display(self, display_id: int | None) -> object:
        return self._update(display_id=display_id)

    def set_every_display(self, on: bool) -> object:
        return self._update(every_display=on)

    def set_root(self, root_id: int | None) -> object:
        return self._update(root_id=root_id)

    def set_missing(self, missing: bool | None) -> object:
        return self._update(missing=missing)

    def set_include_excluded(self, on: bool) -> object:
        return self._update(include_excluded=on)

    def set_include_unusable(self, on: bool) -> object:
        return self._update(include_unusable=on)

    def set_window(self, *, offset: int, limit: int) -> object:
        return self._update(offset=max(0, offset), limit=limit)

    # -- selection --------------------------------------------------------------------------------------

    @property
    def selection(self) -> frozenset[int]:
        return frozenset(self._selection)

    def select(self, image_id: int) -> None:
        self._selection.add(image_id)
        self._emit_state()

    def deselect(self, image_id: int) -> None:
        self._selection.discard(image_id)
        self._emit_state()

    def toggle_selection(self, image_id: int) -> None:
        self._selection.symmetric_difference_update({image_id})
        self._emit_state()

    def clear_selection(self) -> None:
        self._selection.clear()
        self._emit_state()

    # -- loading ----------------------------------------------------------------------------------------

    def refresh(self, cb: Callable[[BrowseState], None] | None = None) -> object:
        self._generation += 1
        generation = self._generation

        def work() -> _Result:
            conn = self._services.read()
            if not self._loaded_defaults:
                self._spec = replace(self._spec, min_long_edge=default_spec(conn).min_long_edge)
                self._loaded_defaults = True
            counts = _counts(segment_counts(conn, self._spec))
            spec = self._spec
            if not self._segment_chosen:
                flip = queries.Segment.IDEAL if counts.ideal > 0 else queries.Segment.ALL
                spec = replace(spec, segment=flip)
            page = fetch_page(conn, spec)
            return _Result(generation, spec, tuple(page.rows), page.total, page.offset, counts)

        def done(result: _Result | None, error: BaseException | None) -> None:
            if error is not None or result is None:
                return
            if result.generation != self._generation:
                return  # a newer refresh superseded this one (search debounce / last-wins)
            self._spec = result.spec
            self._state = BrowseState(
                cards=tuple(_card(row) for row in result.rows),
                total=result.total,
                offset=result.offset,
                segment=result.spec.segment.value,
                search=result.spec.search,
                counts=result.counts,
                selection=frozenset(self._selection),
                loading=False,
            )
            self._notify()
            if cb is not None:
                cb(self._state)

        return run_in_worker(work, done, scheduler=self._scheduler)

    def on_page_shown(self) -> object:
        """Refresh iff another process has written since we last looked (``PRAGMA data_version``)."""

        def work() -> int:
            conn = self._services.read()
            return int(conn.execute("PRAGMA data_version").fetchone()[0])

        def done(version: int | None, error: BaseException | None) -> None:
            if error is not None or version is None:
                return
            if version != self._data_version:
                self._data_version = version
                self.refresh()

        return run_in_worker(work, done, scheduler=self._scheduler)

    def load_thumb(
        self, image_id: int, cb: Callable[[bytes | ThumbPlaceholder], None]
    ) -> object:
        def work() -> bytes | ThumbPlaceholder:
            conn = self._services.read()
            row = get_image(conn, image_id)
            if row is None or row.thumb_key is None:
                reason = "missing" if (row is not None and row.missing) else "none"
                return ThumbPlaceholder(image_id, reason)
            data = self._services.thumbs.read(row.thumb_key, ThumbSize.NORMAL)
            if data is None:
                reason = "missing" if row.missing else "failed"
                return ThumbPlaceholder(image_id, reason)
            return data

        def done(result: bytes | ThumbPlaceholder | None, error: BaseException | None) -> None:
            if error is not None or result is None:
                cb(ThumbPlaceholder(image_id, "failed"))
                return
            cb(result)

        return run_in_worker(work, done, scheduler=self._scheduler)

    # -- exclusions (M1.7: right-click → Exclude Image / Exclude Folder, with undo) ---------------------

    def exclude_image(
        self, image_id: int, *, cb: Callable[[ExcludeOutcome], None] | None = None
    ) -> object:
        """Exclude one image by its exact path (a ``FILE`` rule, inode-pinned so a rename survives).

        The row leaves Browse on its own through the change feed (the default query hides excluded rows);
        the returned :class:`ExcludeOutcome` carries the rule id as the token :meth:`undo_exclusion` takes.
        """

        def work() -> ExcludeOutcome:
            conn = self._services.read()
            row = get_image(conn, image_id)
            if row is None:
                return ExcludeOutcome(False, kind="file", message="image not found")
            try:
                validate_rule(RuleKind.FILE, row.path)
            except PatternError as error:
                return ExcludeOutcome(False, kind="file", message=error.reason)
            rule_id = self._services.writer.submit(
                _exclude_job(RuleKind.FILE, row.path, self._home, device=row.device, inode=row.inode)
            ).result()
            self._services.feed.emit(Change(ChangeKind.RULES_CHANGED))
            return ExcludeOutcome(True, rule_id=str(rule_id), kind="file", label=row.name)

        return self._run_exclude(work, cb)

    def exclude_folder(
        self, image_id: int, *, cb: Callable[[ExcludeOutcome], None] | None = None
    ) -> object:
        """Exclude the image's whole directory (a ``FOLDER`` rule); every card under it leaves Browse."""

        def work() -> ExcludeOutcome:
            conn = self._services.read()
            row = get_image(conn, image_id)
            if row is None:
                return ExcludeOutcome(False, kind="folder", message="image not found")
            try:
                validate_rule(RuleKind.FOLDER, row.dir)
            except PatternError as error:
                return ExcludeOutcome(False, kind="folder", message=error.reason)
            rule_id = self._services.writer.submit(
                _exclude_job(RuleKind.FOLDER, row.dir, self._home)
            ).result()
            self._services.feed.emit(Change(ChangeKind.RULES_CHANGED))
            return ExcludeOutcome(True, rule_id=str(rule_id), kind="folder", label=row.dir)

        return self._run_exclude(work, cb)

    def undo_exclusion(
        self, rule_id: str | int, *, cb: Callable[[ExcludeOutcome], None] | None = None
    ) -> object:
        """Remove the rule an exclude created and re-flag every row, so the excluded card(s) return."""
        target = int(rule_id)

        def work() -> ExcludeOutcome:
            self._services.writer.submit(_undo_job(target, self._home)).result()
            self._services.feed.emit(Change(ChangeKind.RULES_CHANGED))
            return ExcludeOutcome(True, rule_id=str(target))

        return self._run_exclude(work, cb)

    def _run_exclude(
        self, work: Callable[[], ExcludeOutcome], cb: Callable[[ExcludeOutcome], None] | None
    ) -> object:
        def done(result: ExcludeOutcome | None, error: BaseException | None) -> None:
            if cb is None:
                return
            if error is not None or result is None:
                cb(ExcludeOutcome(False, message=str(error) if error is not None else "failed"))
                return
            cb(result)

        return run_in_worker(work, done, scheduler=self._scheduler)

    # -- internals --------------------------------------------------------------------------------------

    def _update(self, **changes: Any) -> object:
        if "offset" not in changes:
            changes["offset"] = 0
        self._spec = replace(self._spec, **changes)
        return self.refresh()

    def _on_change(self, _change: Change) -> None:
        # Runs on the writer thread: collapse a burst into a single scheduled refresh.
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        self._coalesce(self._flush_change)

    def _flush_change(self) -> None:
        self._refresh_scheduled = False
        self.refresh()

    def _emit_state(self) -> None:
        self._state = replace(self._state, selection=frozenset(self._selection))
        self._notify()

    def _notify(self) -> None:
        for observer in list(self._observers):
            observer(self._state)


@dataclass(frozen=True)
class _Result:
    generation: int
    spec: QuerySpec
    rows: tuple[ImageRow, ...]
    total: int
    offset: int
    counts: SegmentCounts


def _card(row: ImageRow) -> ImageCard:
    return ImageCard(
        id=row.id,
        name=row.name,
        path=row.path,
        width=row.width,
        height=row.height,
        aspect=row.aspect,
        format=row.format,
        missing=row.missing,
        excluded=row.excluded_by is not None,
        unusable=row.probe_status != "ok",
        has_thumb=row.thumb_key is not None and row.thumb_status == "ok",
    )


def _reapply(conn: sqlite3.Connection, home: str) -> None:
    """Recompute ``image.excluded_by`` for every row against the current rules — no rescan (D8)."""
    rules, groups = load_rules(conn)
    includes = [row["path"] for row in conn.execute("SELECT path FROM root WHERE enabled = 1")]
    matcher = compile_matcher(rules, groups, includes=includes, home=home)
    apply_exclusions(conn, matcher)


def _exclude_job(
    kind: RuleKind, value: str, home: str, *, device: int | None = None, inode: int | None = None
) -> Callable[[sqlite3.Connection], int]:
    def job(conn: sqlite3.Connection) -> int:
        rule_id = add_rule(conn, kind, value, group=None, root=None, device=device, inode=inode)
        _reapply(conn, home)
        return rule_id

    return job


def _undo_job(rule_id: int, home: str) -> Callable[[sqlite3.Connection], None]:
    def job(conn: sqlite3.Connection) -> None:
        remove_rule(conn, rule_id)
        _reapply(conn, home)

    return job


def _counts(raw: dict[str, int]) -> SegmentCounts:
    per_display = tuple(
        (int(key.split(":", 1)[1]), value) for key, value in raw.items() if key.startswith("display:")
    )
    return SegmentCounts(
        all=raw.get("all", 0),
        ideal=raw.get("ideal", 0),
        near=raw.get("near", 0),
        exact=raw.get("exact", 0),
        larger=raw.get("larger", 0),
        every=raw.get("every", 0),
        per_display=per_display,
    )
