"""``SourcesVM`` — the Sources page's state: roots, volumes, exclusion rules/groups, rule preview,
test-a-path, and the displays strip (M1 §2.9).

Everything a page needs to render Sources arrives as one frozen :class:`SourcesSnapshot`; the transient
operations (pattern preview, test-a-path) answer through their own frozen DTOs. Reads run on a worker
thread against a per-thread read connection; every write goes through the catalogue writer and then
re-evaluates the affected rows (``apply_exclusions``) so an added or removed rule takes effect at once,
with **no rescan** — a change feed emit lets Browse refresh. No ``catalogue``/``scanner`` type escapes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.capability.reasons import ReasonCode
from src.catalogue.db import (
    CatalogueError,
    Change,
    ChangeKind,
    add_rule,
    apply_exclusions,
    load_rules,
    preview_rule,
    remove_rule,
    set_group_enabled,
    set_rule_enabled,
)
from src.catalogue.model import RulePreview
from src.catalogue.queries import target_displays
from src.scanner.exclude import (
    PatternError,
    Rule,
    RuleKind,
    Verdict,
    compile_matcher,
    validate_rule,
)
from src.scanner.roots import MountTable, default_sources, propose_all
from src.util.threads import Scheduler, run_in_worker
from src.viewmodels.services import AppServices

# A candidate rule id far above any autoincrement id, so an existing rule always wins precedence and the
# preview counts only the rows the *new* rule would take out of Browse.
_CANDIDATE_ID = 1 << 60
_GLOB_CHARS = frozenset("*?[")

_DISPLAY_EMPTY_TEXT = (
    "No display detected — declare one with “--display 1920x1080” or connect a monitor, "
    "then rescan so images can be matched to a screen."
)


@dataclass(frozen=True)
class RootInfo:
    path: str
    kind: str
    enabled: bool
    proposed: bool  # True = a suggestion not yet added; False = a stored root
    id: int | None = None
    volume_id: str | None = None
    default_on: bool = False
    reason: str | None = None  # e.g. "network filesystem (nfs)" for a proposal


@dataclass(frozen=True)
class VolumeInfo:
    volume_id: str
    label: str | None
    online: bool
    removable: bool
    network: bool
    fstype: str | None


@dataclass(frozen=True)
class GroupInfo:
    id: int
    key: str
    name: str
    builtin: bool
    locked: bool
    enabled: bool


@dataclass(frozen=True)
class RuleInfo:
    id: int
    kind: str
    value: str
    group_id: int | None
    enabled: bool


@dataclass(frozen=True)
class DisplayInfo:
    name: str
    width: int
    height: int
    scale: float
    primary: bool
    source: str


@dataclass(frozen=True)
class DisplaysStrip:
    displays: tuple[DisplayInfo, ...]
    reason_code: str | None  # DISPLAY_NOT_DETECTED when the last snapshot found no display
    empty_text: str


@dataclass(frozen=True)
class SourcesSnapshot:
    roots: tuple[RootInfo, ...]
    proposals: tuple[RootInfo, ...]
    volumes: tuple[VolumeInfo, ...]
    groups: tuple[GroupInfo, ...]
    rules: tuple[RuleInfo, ...]
    displays: DisplaysStrip


@dataclass(frozen=True)
class PreviewResult:
    """ "This rule would exclude N images in M folders" — or why the pattern was refused."""

    ok: bool
    images: int = 0
    folders: int = 0
    sample_paths: tuple[str, ...] = ()
    error_code: str | None = None  # a PatternErrorCode value when the pattern was refused
    message: str = ""


@dataclass(frozen=True)
class RuleOutcome:
    ok: bool
    rule_id: int | None = None
    error_code: str | None = None  # a PatternErrorCode value, or a CatalogueError class name
    message: str = ""


@dataclass(frozen=True)
class PathTest:
    path: str
    scanned: bool
    rule_id: int | None = None
    rule_value: str | None = None
    group_name: str | None = None
    at: str | None = None
    include: str | None = None


class SourcesVM:
    def __init__(self, services: AppServices) -> None:
        self._services = services
        self._scheduler: Scheduler = services.scheduler
        self._home = str(Path.home())
        self._observers: list[Callable[[SourcesSnapshot], None]] = []
        self._state: SourcesSnapshot | None = None

    # -- observation ------------------------------------------------------------------------------------

    @property
    def state(self) -> SourcesSnapshot | None:
        return self._state

    def add_observer(self, cb: Callable[[SourcesSnapshot], None]) -> Callable[[], None]:
        self._observers.append(cb)

        def remove() -> None:
            if cb in self._observers:
                self._observers.remove(cb)

        return remove

    # -- loading ----------------------------------------------------------------------------------------

    def refresh(self, cb: Callable[[SourcesSnapshot], None] | None = None) -> object:
        return self._run(self._build_snapshot, cb)

    # -- roots ------------------------------------------------------------------------------------------

    def add_root(self, path: str, cb: Callable[[SourcesSnapshot], None] | None = None) -> object:
        absolute = str(Path(path).expanduser().absolute())

        def work() -> SourcesSnapshot:
            self._services.writer.submit(_add_root_job(absolute)).result()
            self._services.feed.emit(Change(ChangeKind.ROOTS_CHANGED))
            return self._build_snapshot()

        return self._run(work, cb)

    def set_root_enabled(
        self, root_id: int, on: bool, cb: Callable[[SourcesSnapshot], None] | None = None
    ) -> object:
        def work() -> SourcesSnapshot:
            self._services.writer.submit(_set_root_enabled_job(root_id, on)).result()
            self._reapply()
            self._services.feed.emit(Change(ChangeKind.ROOTS_CHANGED))
            return self._build_snapshot()

        return self._run(work, cb)

    def remove_root(self, root_id: int, cb: Callable[[SourcesSnapshot], None] | None = None) -> object:
        def work() -> SourcesSnapshot:
            self._services.writer.submit(_remove_root_job(root_id)).result()
            self._reapply()
            self._services.feed.emit(Change(ChangeKind.ROOTS_CHANGED))
            return self._build_snapshot()

        return self._run(work, cb)

    # -- rules & groups -------------------------------------------------------------------------------

    def add_rule(
        self,
        value: str,
        *,
        kind: RuleKind | None = None,
        group: str | None = None,
        root: str | None = None,
        cb: Callable[[RuleOutcome], None] | None = None,
    ) -> object:
        rule_kind = kind if kind is not None else _infer_kind(value)

        def work() -> tuple[RuleOutcome, SourcesSnapshot]:
            try:
                rule_id = self._services.writer.submit(
                    _add_rule_job(rule_kind, value, group, root)
                ).result()
            except PatternError as error:
                return RuleOutcome(False, error_code=error.code.value, message=error.reason), (
                    self._build_snapshot()
                )
            except CatalogueError as error:
                return RuleOutcome(
                    False, error_code=type(error).__name__, message=str(error)
                ), self._build_snapshot()
            self._reapply()
            self._services.feed.emit(Change(ChangeKind.RULES_CHANGED))
            return RuleOutcome(True, rule_id=rule_id), self._build_snapshot()

        return self._run_outcome(work, cb)

    def remove_rule(self, rule_id: int, cb: Callable[[SourcesSnapshot], None] | None = None) -> object:
        def work() -> SourcesSnapshot:
            self._services.writer.submit(lambda c: remove_rule(c, rule_id)).result()
            self._reapply()
            self._services.feed.emit(Change(ChangeKind.RULES_CHANGED))
            return self._build_snapshot()

        return self._run(work, cb)

    def set_rule_enabled(
        self, rule_id: int, on: bool, cb: Callable[[SourcesSnapshot], None] | None = None
    ) -> object:
        def work() -> SourcesSnapshot:
            self._services.writer.submit(lambda c: set_rule_enabled(c, rule_id, on)).result()
            self._reapply()
            self._services.feed.emit(Change(ChangeKind.RULES_CHANGED))
            return self._build_snapshot()

        return self._run(work, cb)

    def set_group_enabled(
        self, name_or_key: str, on: bool, cb: Callable[[RuleOutcome], None] | None = None
    ) -> object:
        def work() -> tuple[RuleOutcome, SourcesSnapshot]:
            try:
                self._services.writer.submit(lambda c: set_group_enabled(c, name_or_key, on)).result()
            except CatalogueError as error:
                return RuleOutcome(
                    False, error_code=type(error).__name__, message=str(error)
                ), self._build_snapshot()
            self._reapply()
            self._services.feed.emit(Change(ChangeKind.RULES_CHANGED))
            return RuleOutcome(True), self._build_snapshot()

        return self._run_outcome(work, cb)

    # -- preview & test-a-path --------------------------------------------------------------------------

    def preview(
        self, value: str, *, kind: RuleKind | None = None, cb: Callable[[PreviewResult], None] | None = None
    ) -> object:
        rule_kind = kind if kind is not None else _infer_kind(value)

        def work() -> PreviewResult:
            try:
                validate_rule(rule_kind, value)
            except PatternError as error:
                return PreviewResult(False, error_code=error.code.value, message=error.reason)
            conn = self._services.read()
            rules, groups = load_rules(conn)
            candidate = Rule(id=_CANDIDATE_ID, kind=rule_kind, value=value)
            includes = _enabled_roots(conn)
            matcher = compile_matcher(
                [*rules, candidate], groups, includes=includes, home=self._home
            )
            result: RulePreview = preview_rule(conn, matcher, _CANDIDATE_ID)
            return PreviewResult(
                True, images=result.images, folders=result.folders, sample_paths=result.sample_paths
            )

        def done(result: PreviewResult | None, error: BaseException | None) -> None:
            if error is not None or result is None:
                return
            if cb is not None:
                cb(result)

        return run_in_worker(work, done, scheduler=self._scheduler)

    def test_path(self, path: str, *, cb: Callable[[PathTest], None] | None = None) -> object:
        absolute = str(Path(path).expanduser().absolute())

        def work() -> PathTest:
            conn = self._services.read()
            rules, groups = load_rules(conn)
            includes = _enabled_roots(conn)
            matcher = compile_matcher(rules, groups, includes=includes, home=self._home)
            verdict: Verdict = matcher.explain(absolute)
            return _path_test(verdict)

        def done(result: PathTest | None, error: BaseException | None) -> None:
            if error is not None or result is None:
                return
            if cb is not None:
                cb(result)

        return run_in_worker(work, done, scheduler=self._scheduler)

    # -- internals --------------------------------------------------------------------------------------

    def _reapply(self) -> None:
        """Recompute ``image.excluded_by`` for every row against the current rules (no rescan)."""
        self._services.writer.submit(self._reapply_job).result()

    def _reapply_job(self, conn: sqlite3.Connection) -> None:
        rules, groups = load_rules(conn)
        includes = _enabled_roots(conn)
        matcher = compile_matcher(rules, groups, includes=includes, home=self._home)
        apply_exclusions(conn, matcher)

    def _build_snapshot(self) -> SourcesSnapshot:
        conn = self._services.read()
        mounts = self._services.mounts()
        return SourcesSnapshot(
            roots=self._roots(conn),
            proposals=self._proposals(conn, mounts),
            volumes=self._volumes(conn),
            groups=self._groups(conn),
            rules=self._rules(conn),
            displays=self._displays(conn),
        )

    def _roots(self, conn: sqlite3.Connection) -> tuple[RootInfo, ...]:
        rows = conn.execute(
            "SELECT id, path, kind, enabled, volume_id FROM root ORDER BY id"
        ).fetchall()
        return tuple(
            RootInfo(
                path=row["path"],
                kind=row["kind"],
                enabled=bool(row["enabled"]),
                proposed=False,
                id=int(row["id"]),
                volume_id=row["volume_id"],
            )
            for row in rows
        )

    def _proposals(self, conn: sqlite3.Connection, mounts: MountTable) -> tuple[RootInfo, ...]:
        known = {row["path"] for row in conn.execute("SELECT path FROM root")}
        sources = default_sources(Path(self._home), Path("/"), mounts)
        out: list[RootInfo] = []
        for proposal in propose_all(sources):
            if proposal.path in known:
                continue
            out.append(
                RootInfo(
                    path=proposal.path,
                    kind=proposal.kind.value,
                    enabled=False,
                    proposed=True,
                    volume_id=proposal.volume_id,
                    default_on=proposal.default_on,
                    reason=proposal.reason,
                )
            )
        return tuple(out)

    def _volumes(self, conn: sqlite3.Connection) -> tuple[VolumeInfo, ...]:
        rows = conn.execute(
            "SELECT volume_id, label, fstype, removable, network, online FROM volume ORDER BY volume_id"
        ).fetchall()
        return tuple(
            VolumeInfo(
                volume_id=row["volume_id"],
                label=row["label"],
                online=bool(row["online"]),
                removable=bool(row["removable"]),
                network=bool(row["network"]),
                fstype=row["fstype"],
            )
            for row in rows
        )

    def _groups(self, conn: sqlite3.Connection) -> tuple[GroupInfo, ...]:
        _rules, groups = load_rules(conn)
        return tuple(
            GroupInfo(g.id, g.key, g.name, g.builtin, g.locked, g.enabled) for g in groups
        )

    def _rules(self, conn: sqlite3.Connection) -> tuple[RuleInfo, ...]:
        rules, _groups = load_rules(conn)
        return tuple(
            RuleInfo(r.id, r.kind.value, r.value, r.group_id, r.enabled) for r in rules
        )

    def _displays(self, conn: sqlite3.Connection) -> DisplaysStrip:
        displays = tuple(
            DisplayInfo(d.name, d.width, d.height, d.scale, d.is_primary, d.source)
            for d in target_displays(conn)
        )
        if displays:
            return DisplaysStrip(displays, reason_code=None, empty_text="")
        return DisplaysStrip(
            (), reason_code=ReasonCode.DISPLAY_NOT_DETECTED.value, empty_text=_DISPLAY_EMPTY_TEXT
        )

    def _run(
        self, work: Callable[[], SourcesSnapshot], cb: Callable[[SourcesSnapshot], None] | None
    ) -> object:
        def done(snapshot: SourcesSnapshot | None, error: BaseException | None) -> None:
            if error is not None or snapshot is None:
                return
            self._set(snapshot)
            if cb is not None:
                cb(snapshot)

        return run_in_worker(work, done, scheduler=self._scheduler)

    def _run_outcome(
        self,
        work: Callable[[], tuple[RuleOutcome, SourcesSnapshot]],
        cb: Callable[[RuleOutcome], None] | None,
    ) -> object:
        def done(
            result: tuple[RuleOutcome, SourcesSnapshot] | None, error: BaseException | None
        ) -> None:
            if error is not None or result is None:
                return
            outcome, snapshot = result
            self._set(snapshot)
            if cb is not None:
                cb(outcome)

        return run_in_worker(work, done, scheduler=self._scheduler)

    def _set(self, snapshot: SourcesSnapshot) -> None:
        self._state = snapshot
        for observer in list(self._observers):
            observer(snapshot)


# ── module helpers ───────────────────────────────────────────────────────────────────────────────────────


def _infer_kind(value: str) -> RuleKind:
    return RuleKind.PATTERN if any(ch in _GLOB_CHARS for ch in value) else RuleKind.FOLDER


def _enabled_roots(conn: sqlite3.Connection) -> list[str]:
    return [row["path"] for row in conn.execute("SELECT path FROM root WHERE enabled = 1")]


def _path_test(verdict: Verdict) -> PathTest:
    return PathTest(
        path=verdict.path,
        scanned=verdict.scanned,
        rule_id=None if verdict.hit is None else verdict.hit.rule_id,
        rule_value=None if verdict.rule is None else verdict.rule.value,
        group_name=None if verdict.group is None else verdict.group.name,
        at=verdict.at,
        include=verdict.include,
    )


def _add_root_job(absolute: str) -> Callable[[sqlite3.Connection], int]:
    def job(conn: sqlite3.Connection) -> int:
        existing = conn.execute("SELECT id FROM root WHERE path = ?", (absolute,)).fetchone()
        if existing is not None:
            conn.execute("UPDATE root SET enabled = 1 WHERE id = ?", (existing[0],))
            return int(existing[0])
        cursor = conn.execute("INSERT INTO root(path, kind, enabled) VALUES (?, 'user', 1)", (absolute,))
        return int(cursor.lastrowid or 0)

    return job


def _set_root_enabled_job(root_id: int, on: bool) -> Callable[[sqlite3.Connection], None]:
    def job(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE root SET enabled = ? WHERE id = ?", (int(on), root_id))

    return job


def _remove_root_job(root_id: int) -> Callable[[sqlite3.Connection], None]:
    def job(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM root WHERE id = ?", (root_id,))

    return job


def _add_rule_job(
    kind: RuleKind, value: str, group: str | None, root: str | None
) -> Callable[[sqlite3.Connection], int]:
    def job(conn: sqlite3.Connection) -> int:
        return add_rule(conn, kind, value, group=group, root=root)

    return job
