"""Scan orchestration: the single catalogue writer thread and the ``ScanService`` pipeline (M1 §2.9, §3).

Two responsibilities live here, both service-side (no ``gi``):

* :class:`CatalogueWriter` — the one thread that owns the process's only write connection. Every mutation
  (scan batches, display snapshots, rule/pin/setting writes done through it) runs inside exactly one
  ``db.transaction`` (P4-3: one transaction per job, never ``executescript``). ``submit`` hands back a
  ``Future`` so callers can wait for a commit; ``close`` drains the queue and joins the thread.

* :class:`ScanService` — turns a set of roots into catalogue rows. It never touches the write connection
  directly: it *submits* short jobs to the writer. Per scan it holds the non-blocking scan ``flock`` (a
  second scanner gets :class:`~src.catalogue.db.ScanInProgressError` at once, never a deadlock), heals
  volume paths by UUID, detects the displays, then for each enabled root runs one walker thread feeding a
  bounded queue, ``N = min(4, cpu)`` probe workers on a **scan-private** pool feeding a second bounded
  queue, and a batching consumer that commits ``≤ 200`` rows (or every ``250 ms``) at a time. Missing rows
  are marked only after a *complete, uncancelled* walk and never beneath a directory that failed to list.

Threading and crash-safety (contract §3): the shared ``util.threads`` pool is left free for the UI; the
scan pool is created and shut down inside :meth:`ScanService.scan`; on cancel the walk stops, the queues
drain without probing, the open batch still commits and the scan is recorded ``cancelled`` with **no**
missing-marking; a ``kill -9`` leaves committed batches in the WAL and the next ``open_catalogue`` →
``recover`` marks the abandoned scan ``interrupted``, after which a rescan converges to the same rows.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from src.catalogue import ideal
from src.catalogue.db import (
    CatalogueError,
    Change,
    ChangeFeed,
    ChangeKind,
    connect,
    get_setting,
    load_rules,
    save_display_snapshot,
    scan_lock,
    transaction,
)
from src.catalogue.ideal import DEFAULT_THRESHOLD_PCT
from src.catalogue.thumbs import ThumbCache
from src.scanner import probe, walker
from src.scanner.displays import Display, DisplayDetection, DisplayProbe, detect
from src.scanner.exclude import Matcher, RuleHit, compile_matcher
from src.scanner.probe import DecodeBudget, ProbeResult
from src.scanner.roots import MountTable
from src.scanner.walker import Candidate, FileKey, ScanIssue, WalkOptions, WalkResult
from src.util.cancel import CancelToken

T = TypeVar("T")

_BATCH_ROWS = 200
_BATCH_SECONDS = 0.25
_CAND_QUEUE = 512
_RESULT_QUEUE = 256
_QUEUE_POLL = 0.2
_PROGRESS_HZ = 0.1
_ISSUE_SAMPLE_CAP = 500


# ── the writer thread ────────────────────────────────────────────────────────────────────────────────────


@dataclass
class _Job:
    fn: Callable[[sqlite3.Connection], object]
    future: Future[object]


class CatalogueWriter:
    """The one writer thread: it owns the sole write connection and runs each job in one transaction."""

    def __init__(self, db_path: Path, feed: ChangeFeed) -> None:
        self._db_path = Path(db_path)
        self._feed = feed
        self._queue: queue.Queue[_Job | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="lwp-writer", daemon=True)
        self._lock = threading.Lock()
        self._started = False
        self._closed = False

    @property
    def feed(self) -> ChangeFeed:
        return self._feed

    def submit(self, fn: Callable[[sqlite3.Connection], T]) -> Future[T]:
        """Run ``fn`` on the writer thread in one ``BEGIN IMMEDIATE … COMMIT``; the ``Future`` carries it."""
        with self._lock:
            if self._closed:
                raise CatalogueError("the catalogue writer is closed")
            if not self._started:
                self._started = True
                self._thread.start()
        future: Future[object] = Future()
        self._queue.put(_Job(fn, future))
        return future  # type: ignore[return-value]

    def _run(self) -> None:
        conn = connect(self._db_path)
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    return
                if not job.future.set_running_or_notify_cancel():
                    continue
                try:
                    with transaction(conn):
                        result = job.fn(conn)
                except BaseException as error:
                    job.future.set_exception(error)
                else:
                    job.future.set_result(result)
        finally:
            conn.close()

    def close(self, timeout: float = 5.0) -> None:
        """Drain the queue and join the thread, so nothing outlives the process (contract §3)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            started = self._started
        if started:
            self._queue.put(None)
            self._thread.join(timeout)


# ── progress / summary DTOs ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScanProgress:
    scan_id: int
    dirs: int
    found: int
    unchanged: int
    probed: int
    ideal: int
    excluded: int
    issues: int
    walk_done: bool
    current_dir: str


@dataclass(frozen=True)
class ScanSummary:
    scan_id: int
    result: str
    progress: ScanProgress
    detection: DisplayDetection
    seconds: float


class ScanListener(Protocol):
    def on_progress(self, p: ScanProgress) -> None: ...  # ≤ 10 Hz, on a worker thread


# ── internal pipeline items and state ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Unchanged:
    path: str


@dataclass(frozen=True)
class _Moved:
    candidate: Candidate


_ResultItem = ProbeResult | _Unchanged | _Moved


@dataclass(frozen=True)
class _Root:
    id: int
    path: str
    kind: str
    volume_id: str | None
    stable_inodes: bool


class _KnownFiles:
    """The walker's read-only snapshot of what the catalogue already knows (ruling Q15).

    ``key_for`` is restricted to the root being walked; ``by_inode`` spans the whole catalogue so a file
    moved between roots is recognised once, never re-probed or duplicated.
    """

    def __init__(
        self, keys: dict[str, FileKey], inodes: dict[tuple[int, int], tuple[int, str, FileKey]]
    ) -> None:
        self._keys = keys
        self._inodes = inodes

    def key_for(self, path: str) -> FileKey | None:
        return self._keys.get(path)

    def by_inode(self, device: int, inode: int) -> tuple[int, str, FileKey] | None:
        return self._inodes.get((device, inode))


@dataclass
class _Counters:
    lock: threading.Lock = field(default_factory=threading.Lock)
    dirs: int = 0
    found: int = 0
    unchanged: int = 0
    probed: int = 0
    ideal: int = 0
    skipped: int = 0
    issues: int = 0
    current_dir: str = ""
    walk_done: bool = False
    skips: dict[int, list[int]] = field(default_factory=dict)  # rule_id -> [dirs, files]
    issue_counts: dict[str, int] = field(default_factory=dict)
    issue_samples: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


class _Abort:
    """A scan-wide teardown signal, distinct from a user cancel. Set when a writer job fails for a
    non-cancel reason (a locked/corrupt/full catalogue): producers then enter drain mode and every
    ``_put`` / ``pool.shutdown`` returns promptly, so a broken writer can never hang the pipeline (§3).
    The first failure is remembered so the scan can be recorded ``error`` carrying it."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.error: BaseException | None = None

    def trigger(self, error: BaseException) -> None:
        if self.error is None:
            self.error = error
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


def _split(path: str) -> tuple[str, str]:
    cut = path.rfind("/")
    if cut <= 0:
        return "/", path[cut + 1 :]
    return path[:cut], path[cut + 1 :]


def _now() -> int:
    return int(time.time())


# ── small SQL helpers, each run inside a writer job ───────────────────────────────────────────────────────

_UPSERT_IMAGE = """
INSERT INTO image(path, dir, name, root_id, volume_id, device, inode, mtime_ns, size,
  width, height, exif_orientation, format, has_alpha, is_animated, has_icc, aspect, megapixels,
  probe_status, probe_error, thumb_key, thumb_status, first_seen, last_seen, seen_scan, missing)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,  ?, ?, ?, ?, ?, ?, ?, ?, ?,  ?, ?, ?, ?,  ?, ?, ?, 0)
ON CONFLICT(path) DO UPDATE SET
  dir = excluded.dir, name = excluded.name, root_id = excluded.root_id, volume_id = excluded.volume_id,
  device = excluded.device, inode = excluded.inode, mtime_ns = excluded.mtime_ns, size = excluded.size,
  width = excluded.width, height = excluded.height, exif_orientation = excluded.exif_orientation,
  format = excluded.format, has_alpha = excluded.has_alpha, is_animated = excluded.is_animated,
  has_icc = excluded.has_icc, aspect = excluded.aspect, megapixels = excluded.megapixels,
  probe_status = excluded.probe_status, probe_error = excluded.probe_error,
  thumb_key = excluded.thumb_key, thumb_status = excluded.thumb_status,
  last_seen = excluded.last_seen, seen_scan = excluded.seen_scan, missing = 0
"""


def _upsert_image(
    conn: sqlite3.Connection, r: ProbeResult, root_id: int, volume_id: str | None, scan_id: int, now: int
) -> int:
    path = r.candidate.path
    dir_path, name = _split(path)
    dev, ino, mtime_ns, size = r.key
    width = r.width or None
    height = r.height or None
    aspect = (width / height) if (width and height) else None
    megapixels = (width * height / 1_000_000.0) if (width and height) else None
    conn.execute(
        _UPSERT_IMAGE,
        (
            path,
            dir_path,
            name,
            root_id,
            volume_id,
            dev,
            ino,
            mtime_ns,
            size,
            width,
            height,
            r.exif_orientation,
            r.format or None,
            int(r.has_alpha),
            int(r.is_animated),
            int(r.has_icc),
            aspect,
            megapixels,
            r.status.value,
            r.error or None,
            r.thumb_key,
            r.thumb_status,
            now,
            now,
            scan_id,
        ),
    )
    row = conn.execute("SELECT id FROM image WHERE path = ?", (path,)).fetchone()
    return int(row[0])


def _mark_missing(conn: sqlite3.Connection, root_id: int, scan_id: int, failed_dirs: Sequence[str]) -> int:
    """After a complete walk: mark this root's unseen, non-excluded rows missing — except beneath a
    directory that failed to list (nothing under it was walked, so its absence proves nothing)."""
    prefixes = tuple(fd.rstrip("/") for fd in failed_dirs)
    to_mark: list[tuple[int]] = []
    seen: list[tuple[int]] = []
    for row in conn.execute(
        "SELECT id, path, seen_scan, missing FROM image WHERE root_id = ? AND excluded_by IS NULL",
        (root_id,),
    ):
        if row["seen_scan"] == scan_id:
            if row["missing"]:
                seen.append((row["id"],))
            continue
        path = row["path"]
        if any(path == fd or path.startswith(fd + "/") for fd in prefixes):
            continue
        if not row["missing"]:
            to_mark.append((row["id"],))
    conn.executemany("UPDATE image SET missing = 1 WHERE id = ?", to_mark)
    conn.executemany("UPDATE image SET missing = 0 WHERE id = ?", seen)
    return len(to_mark)


def _mark_volume_missing(conn: sqlite3.Connection, root_id: int) -> int:
    """An offline volume cannot be walked; its non-excluded rows are missing until it comes back."""
    cursor = conn.execute(
        "UPDATE image SET missing = 1 WHERE root_id = ? AND excluded_by IS NULL AND missing = 0", (root_id,)
    )
    return int(cursor.rowcount)


def _load_known(
    conn: sqlite3.Connection, root_id: int
) -> tuple[dict[str, FileKey], dict[tuple[int, int], tuple[int, str, FileKey]]]:
    keys: dict[str, FileKey] = {}
    for row in conn.execute(
        "SELECT path, device, inode, mtime_ns, size FROM image WHERE root_id = ?", (root_id,)
    ):
        if None in (row["device"], row["inode"], row["mtime_ns"], row["size"]):
            continue
        keys[row["path"]] = (row["device"], row["inode"], row["mtime_ns"], row["size"])
    inodes: dict[tuple[int, int], tuple[int, str, FileKey]] = {}
    for row in conn.execute(
        "SELECT id, path, device, inode, mtime_ns, size FROM image "
        "WHERE device IS NOT NULL AND inode IS NOT NULL AND mtime_ns IS NOT NULL AND size IS NOT NULL"
    ):
        key: FileKey = (row["device"], row["inode"], row["mtime_ns"], row["size"])
        inodes[(row["device"], row["inode"])] = (row["id"], row["path"], key)
    return keys, inodes


def _mark_volume_missing_job(root_id: int) -> Callable[[sqlite3.Connection], int]:
    def job(conn: sqlite3.Connection) -> int:
        return _mark_volume_missing(conn, root_id)

    return job


def _mark_missing_job(
    root_id: int, scan_id: int, failed_dirs: Sequence[str]
) -> Callable[[sqlite3.Connection], int]:
    def job(conn: sqlite3.Connection) -> int:
        return _mark_missing(conn, root_id, scan_id, failed_dirs)

    return job


def _load_known_job(
    root_id: int,
) -> Callable[
    [sqlite3.Connection],
    tuple[dict[str, FileKey], dict[tuple[int, int], tuple[int, str, FileKey]]],
]:
    def job(
        conn: sqlite3.Connection,
    ) -> tuple[dict[str, FileKey], dict[tuple[int, int], tuple[int, str, FileKey]]]:
        return _load_known(conn, root_id)

    return job


def _stamp_root_job(root_id: int, scan_id: int, now: int) -> Callable[[sqlite3.Connection], None]:
    def job(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE root SET last_scan = ?, last_scan_id = ? WHERE id = ?", (now, scan_id, root_id)
        )

    return job


def _load_roots(conn: sqlite3.Connection, root_ids: Sequence[int] | None) -> list[_Root]:
    wanted = None if root_ids is None else set(root_ids)
    roots: list[_Root] = []
    for row in conn.execute(
        "SELECT r.id, r.path, r.kind, r.enabled, r.volume_id, v.stable_inodes "
        "FROM root r LEFT JOIN volume v ON v.volume_id = r.volume_id ORDER BY r.id"
    ):
        if not row["enabled"]:
            continue
        if wanted is not None and row["id"] not in wanted:
            continue
        stable = True if row["stable_inodes"] is None else bool(row["stable_inodes"])
        roots.append(_Root(row["id"], row["path"], row["kind"], row["volume_id"], stable))
    return roots


def _reconcile_volumes(conn: sqlite3.Connection, mounts: MountTable, now: int) -> set[int]:
    """Update volume online-state, heal a moved volume root (and its image paths) by UUID, and report the
    ids of volume roots whose drive is currently offline."""
    offline: set[int] = set()
    for row in conn.execute("SELECT id, path, volume_id FROM root WHERE volume_id IS NOT NULL"):
        vid = row["volume_id"]
        mount = mounts.by_uuid(vid)
        if mount is None:
            offline.add(row["id"])
            conn.execute("UPDATE volume SET online = 0, last_seen = ? WHERE volume_id = ?", (now, vid))
            continue
        conn.execute(
            "INSERT INTO volume(volume_id, label, fstype, last_mount, removable, network, stable_inodes, "
            "online, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?) "
            "ON CONFLICT(volume_id) DO UPDATE SET label = excluded.label, fstype = excluded.fstype, "
            "last_mount = excluded.last_mount, removable = excluded.removable, network = excluded.network, "
            "stable_inodes = excluded.stable_inodes, online = 1, last_seen = excluded.last_seen",
            (
                vid,
                mount.label,
                mount.fstype,
                mount.target,
                int(mount.removable),
                int(mount.network),
                int(mount.stable_inodes),
                now,
            ),
        )
        if mount.target != row["path"]:
            conn.execute("UPDATE root SET path = ? WHERE id = ?", (mount.target, row["id"]))
            _heal_paths(conn, vid, row["path"], mount.target)
    return offline


def _heal_paths(conn: sqlite3.Connection, volume_id: str, old: str, new: str) -> None:
    old = old.rstrip("/")
    new = new.rstrip("/")
    updates: list[tuple[str, str, int]] = []
    for row in conn.execute("SELECT id, path FROM image WHERE volume_id = ?", (volume_id,)):
        path = row["path"]
        if path == old or path.startswith(old + "/"):
            new_path = new + path[len(old) :]
            new_dir, _name = _split(new_path)
            updates.append((new_path, new_dir, row["id"]))
    conn.executemany("UPDATE image SET path = ?, dir = ? WHERE id = ?", updates)


# ── the walk listener (runs on the walker thread) ────────────────────────────────────────────────────────


class _WalkListener:
    def __init__(
        self,
        counters: _Counters,
        service: ScanService,
        res_q: queue.Queue[_ResultItem | None],
        cancel: CancelToken,
        abort: _Abort,
    ) -> None:
        self._c = counters
        self._service = service
        self._res_q = res_q
        self._cancel = cancel
        self._abort = abort

    def on_dir(self, path: str, candidates: int) -> None:
        with self._c.lock:
            self._c.dirs += 1
            self._c.current_dir = path

    def on_skip(self, hit: RuleHit, is_dir: bool) -> None:
        with self._c.lock:
            self._c.skipped += 1
            counts = self._c.skips.setdefault(hit.rule_id, [0, 0])
            counts[0 if is_dir else 1] += 1

    def on_unchanged(self, path: str) -> None:
        self._service._put(self._res_q, _Unchanged(path), self._cancel, self._abort)

    def on_issue(self, issue: ScanIssue) -> None:
        with self._c.lock:
            self._c.issues += 1
            kind = issue.kind.value
            self._c.issue_counts[kind] = self._c.issue_counts.get(kind, 0) + 1
            samples = self._c.issue_samples.setdefault(kind, [])
            if len(samples) < _ISSUE_SAMPLE_CAP:
                samples.append((issue.path, issue.detail))


# ── the service ──────────────────────────────────────────────────────────────────────────────────────────


class ScanService:
    def __init__(
        self,
        db_path: Path,
        writer: CatalogueWriter,
        thumbs: ThumbCache,
        probes: Sequence[DisplayProbe],
        mounts: Callable[[], MountTable],
    ) -> None:
        self._db_path = Path(db_path)
        self._writer = writer
        self._thumbs = thumbs
        self._probes = list(probes)
        self._mounts = mounts
        self._home = str(Path.home())
        self._budget = DecodeBudget()

    # -- public API -------------------------------------------------------------------------------------

    def scan(
        self,
        root_ids: Sequence[int] | None,
        declared: Sequence[Display],
        listener: ScanListener,
        cancel: CancelToken,
    ) -> ScanSummary:
        started = time.monotonic()
        counters = _Counters()
        with scan_lock(self._db_path):  # non-blocking: a second scanner raises ScanInProgressError at once
            mounts = self._mounts()
            now = _now()
            offline = self._writer.submit(lambda c: _reconcile_volumes(c, mounts, now)).result()
            detection = detect(self._probes, list(declared))
            scan_id, changed, roots, options, threshold = self._begin(root_ids, detection, mounts, now)
            if changed:
                self._writer.feed.emit(Change(ChangeKind.DISPLAYS_CHANGED, scan_id=scan_id))
            matcher = self._matcher(mounts)
            abort = _Abort()
            result_state = "ok"
            error: BaseException | None = None
            try:
                self._run_roots(
                    roots, offline, scan_id, matcher, options, threshold, counters, listener, cancel, abort
                )
                if cancel.cancelled:
                    result_state = "cancelled"
            except BaseException as exc:  # a writer/pipeline failure: tear down cleanly, record 'error'
                result_state = "error"
                error = abort.error or exc
                abort.trigger(exc)  # release any producer still blocked on a full queue
                cancel.cancel()  # stop the walker too (its only stop signal is the cancel token)
                if not isinstance(exc, Exception):
                    raise  # KeyboardInterrupt / SystemExit: record below in `finally`, then propagate
            finally:
                if result_state == "ok":
                    with contextlib.suppress(Exception):
                        self._thumbs.evict()
                with contextlib.suppress(Exception):  # never let finishing mask the teardown
                    self._finish(scan_id, result_state, detection, counters, error)
        progress = self._progress(scan_id, counters)
        return ScanSummary(scan_id, result_state, progress, detection, time.monotonic() - started)

    def refresh_displays(self, declared: Sequence[Display] = ()) -> DisplayDetection:
        """Re-measure the desktop and re-judge from stored dimensions only — opens no image."""
        detection = detect(self._probes, list(declared))
        now = _now()

        def job(conn: sqlite3.Connection) -> bool:
            _ids, changed = save_display_snapshot(conn, detection, now)
            if changed:
                threshold = get_setting(conn, "ideal.threshold_pct", DEFAULT_THRESHOLD_PCT)
                ideal.rebuild(conn, threshold, None)
            return changed

        changed = self._writer.submit(job).result()
        if changed:
            self._writer.feed.emit(Change(ChangeKind.DISPLAYS_CHANGED))
        return detection

    # -- setup ------------------------------------------------------------------------------------------

    def _begin(
        self,
        root_ids: Sequence[int] | None,
        detection: DisplayDetection,
        mounts: MountTable,
        now: int,
    ) -> tuple[int, bool, list[_Root], WalkOptions, int]:
        def job(conn: sqlite3.Connection) -> tuple[int, bool, list[_Root], WalkOptions, int]:
            _ids, changed = save_display_snapshot(conn, detection, now)
            threshold = get_setting(conn, "ideal.threshold_pct", DEFAULT_THRESHOLD_PCT)
            min_bytes = get_setting(conn, "scan.min_file_bytes", 65_536)
            max_bytes = get_setting(conn, "scan.max_file_bytes", 268_435_456)
            options = WalkOptions(min_file_bytes=min_bytes, max_file_bytes=max_bytes)
            roots = _load_roots(conn, root_ids)
            scan_id = int(
                conn.execute(
                    "INSERT INTO scan(started, pid, root_ids, display_set, threshold_pct, reason, result) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'running')",
                    (
                        now,
                        os.getpid(),
                        json.dumps([r.id for r in roots]),
                        json.dumps([f"{d.width}x{d.height}" for d in detection.displays]),
                        threshold,
                        _reason_json(detection),
                    ),
                ).lastrowid
                or 0
            )
            if changed:
                ideal.rebuild(conn, threshold, None)
            return scan_id, changed, roots, options, threshold

        return self._writer.submit(job).result()

    def _matcher(self, mounts: MountTable) -> Matcher:
        def job(conn: sqlite3.Connection) -> tuple[list[object], list[object], list[str]]:
            rules, groups = load_rules(conn)
            includes = [row["path"] for row in conn.execute("SELECT path FROM root WHERE enabled = 1")]
            return list(rules), list(groups), includes

        rules, groups, includes = self._writer.submit(job).result()
        mount_map = {m.uuid: m.target for m in mounts.mounts if m.uuid}
        return compile_matcher(
            rules, groups, includes=includes, home=self._home, mounts=mount_map  # type: ignore[arg-type]
        )

    # -- per-root pipeline ------------------------------------------------------------------------------

    def _run_roots(
        self,
        roots: list[_Root],
        offline: set[int],
        scan_id: int,
        matcher: Matcher,
        options: WalkOptions,
        threshold: int,
        counters: _Counters,
        listener: ScanListener,
        cancel: CancelToken,
        abort: _Abort,
    ) -> None:
        workers = min(4, os.cpu_count() or 1)
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lwp-probe")
        try:
            for root in roots:
                if cancel.cancelled or abort.is_set():
                    break
                now = _now()
                if root.id in offline:
                    self._writer.submit(_mark_volume_missing_job(root.id)).result()
                    self._writer.submit(_stamp_root_job(root.id, scan_id, now)).result()
                    continue
                keys, inodes = self._writer.submit(_load_known_job(root.id)).result()
                known = _KnownFiles(keys, inodes)
                walk_result = self._scan_one(
                    root,
                    scan_id,
                    matcher,
                    options,
                    threshold,
                    known,
                    counters,
                    listener,
                    cancel,
                    abort,
                    pool,
                    workers,
                )
                if not cancel.cancelled and walk_result is not None and walk_result.complete:
                    self._writer.submit(
                        _mark_missing_job(root.id, scan_id, walk_result.failed_dirs)
                    ).result()
                self._writer.submit(_stamp_root_job(root.id, scan_id, now)).result()
        finally:
            pool.shutdown(wait=True)

    def _scan_one(
        self,
        root: _Root,
        scan_id: int,
        matcher: Matcher,
        options: WalkOptions,
        threshold: int,
        known: _KnownFiles,
        counters: _Counters,
        listener: ScanListener,
        cancel: CancelToken,
        abort: _Abort,
        pool: ThreadPoolExecutor,
        workers: int,
    ) -> WalkResult | None:
        cand_q: queue.Queue[Candidate | None] = queue.Queue(_CAND_QUEUE)
        res_q: queue.Queue[_ResultItem | None] = queue.Queue(_RESULT_QUEUE)
        walk_listener = _WalkListener(counters, self, res_q, cancel, abort)
        holder: dict[str, WalkResult] = {}

        def run_walk() -> None:
            try:
                holder["result"] = walker.walk(
                    root.path,
                    matcher,
                    known,
                    cand_q,
                    walk_listener,
                    cancel,
                    options,
                    stable_inodes=root.stable_inodes,
                )
            finally:
                with counters.lock:
                    counters.walk_done = True

        walk_thread = threading.Thread(target=run_walk, name="lwp-walk")
        walk_thread.start()
        probe_futures = [
            pool.submit(self._probe_worker, cand_q, res_q, cancel, abort) for _ in range(workers)
        ]

        def finalize() -> None:
            for future in probe_futures:
                future.result()
            walk_thread.join()
            while True:  # deliver the end sentinel, but never block forever if the consumer has gone
                try:
                    res_q.put(None, timeout=_QUEUE_POLL)
                    return
                except queue.Full:
                    if abort.is_set():
                        return  # the consumer raised on a writer failure; no one is left to read it

        fin_thread = threading.Thread(target=finalize, name="lwp-fin")
        fin_thread.start()

        try:
            self._consume(res_q, scan_id, root, threshold, counters, listener, cancel, abort)
        finally:
            # always reap the pipeline threads, even when a flush failure unwound the consumer
            fin_thread.join()
            walk_thread.join()
        return holder.get("result")

    def _probe_worker(
        self,
        cand_q: queue.Queue[Candidate | None],
        res_q: queue.Queue[_ResultItem | None],
        cancel: CancelToken,
        abort: _Abort,
    ) -> None:
        while True:
            try:
                item = cand_q.get(timeout=_QUEUE_POLL)
            except queue.Empty:
                if cancel.cancelled or abort.is_set():
                    return
                continue
            if item is None:
                cand_q.put(None)  # let the sibling workers see the sentinel too
                return
            if cancel.cancelled or abort.is_set():
                continue  # drain the queue WITHOUT probing (cancel §3, or a writer-failure teardown)
            if item.moved_from_id is not None:
                self._put(res_q, _Moved(item), cancel, abort)  # a rename: no re-probe (contract §2.7)
            else:
                result = probe.probe_file(item, self._budget, self._thumbs, cancel)
                self._put(res_q, result, cancel, abort)

    def _consume(
        self,
        res_q: queue.Queue[_ResultItem | None],
        scan_id: int,
        root: _Root,
        threshold: int,
        counters: _Counters,
        listener: ScanListener,
        cancel: CancelToken,
        abort: _Abort,
    ) -> None:
        batch: list[_ResultItem] = []
        last_flush = time.monotonic()
        last_progress = 0.0
        while True:
            try:
                item: _ResultItem | object | None = res_q.get(timeout=_BATCH_SECONDS)
            except queue.Empty:
                item = _TICK
            if item is None:
                if batch:
                    self._flush(batch, scan_id, root, threshold, counters, cancel, abort)
                break
            if item is _TICK:
                if batch and time.monotonic() - last_flush >= _BATCH_SECONDS:
                    self._flush(batch, scan_id, root, threshold, counters, cancel, abort)
                    batch = []
                    last_flush = time.monotonic()
            else:
                batch.append(item)  # type: ignore[arg-type]
                if len(batch) >= _BATCH_ROWS:
                    self._flush(batch, scan_id, root, threshold, counters, cancel, abort)
                    batch = []
                    last_flush = time.monotonic()
            moment = time.monotonic()
            if moment - last_progress >= _PROGRESS_HZ:
                listener.on_progress(self._progress(scan_id, counters))
                last_progress = moment

    def _flush(
        self,
        batch: list[_ResultItem],
        scan_id: int,
        root: _Root,
        threshold: int,
        counters: _Counters,
        cancel: CancelToken,
        abort: _Abort,
    ) -> None:
        items = list(batch)
        now = _now()

        def job(conn: sqlite3.Connection) -> tuple[list[int], int, int, int, int]:
            upserted: list[int] = []
            unchanged = probed = moved = 0
            for item in items:
                if isinstance(item, _Unchanged):
                    conn.execute(
                        "UPDATE image SET seen_scan = ?, last_seen = ?, missing = 0 "
                        "WHERE root_id = ? AND path = ?",
                        (scan_id, now, root.id, item.path),
                    )
                    unchanged += 1
                elif isinstance(item, _Moved):
                    candidate = item.candidate
                    new_dir, new_name = _split(candidate.path)
                    conn.execute(
                        "UPDATE image SET path = ?, dir = ?, name = ?, seen_scan = ?, last_seen = ?, "
                        "missing = 0 WHERE id = ?",
                        (candidate.path, new_dir, new_name, scan_id, now, candidate.moved_from_id),
                    )
                    if candidate.moved_from_id is not None:
                        upserted.append(candidate.moved_from_id)
                    moved += 1
                else:
                    upserted.append(_upsert_image(conn, item, root.id, root.volume_id, scan_id, now))
                    probed += 1
            ideal_in_batch = 0
            if upserted:
                ideal.rebuild(conn, threshold, upserted)
                ideal_in_batch = int(
                    conn.execute(
                        "SELECT count(DISTINCT image_id) FROM ideal_image "
                        "WHERE verdict = 'ideal' AND image_id IN (SELECT value FROM json_each(?))",
                        (json.dumps(upserted),),
                    ).fetchone()[0]
                )
            return upserted, unchanged, probed, moved, ideal_in_batch

        try:
            upserted, unchanged, probed, moved, ideal_in_batch = self._writer.submit(job).result()
        except BaseException as error:
            # the writer failed for a non-cancel reason (locked/corrupt/full catalogue): abort the whole
            # pipeline so no probe worker blocks on a full queue, stop the walker, then surface the failure
            abort.trigger(error)
            cancel.cancel()
            raise
        with counters.lock:
            counters.probed += probed
            counters.found += probed + moved
            counters.unchanged += unchanged
            counters.ideal += ideal_in_batch
        if upserted:
            self._writer.feed.emit(Change(ChangeKind.IMAGES_UPSERTED, tuple(upserted), scan_id))

    # -- finish -----------------------------------------------------------------------------------------

    def _finish(
        self,
        scan_id: int,
        result_state: str,
        detection: DisplayDetection,
        counters: _Counters,
        error: BaseException | None = None,
    ) -> None:
        reason = _reason_json(detection)
        if result_state == "error" and error is not None:
            reason = json.dumps({"error": type(error).__name__, "detail": str(error)[:500]})

        def job(conn: sqlite3.Connection) -> None:
            with counters.lock:
                skips = dict(counters.skips)
                issue_counts = dict(counters.issue_counts)
                issue_samples = {k: list(v) for k, v in counters.issue_samples.items()}
                found, probed, unchanged, skipped = (
                    counters.found,
                    counters.probed,
                    counters.unchanged,
                    counters.skipped,
                )
            for rule_id, (dirs, files) in skips.items():
                conn.execute(
                    "INSERT INTO scan_skip(scan_id, rule_id, dirs, files) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(scan_id, rule_id) DO UPDATE SET "
                    "dirs = excluded.dirs, files = excluded.files",
                    (scan_id, rule_id, dirs, files),
                )
            for kind, samples in issue_samples.items():
                for path, detail in samples[:_ISSUE_SAMPLE_CAP]:
                    conn.execute(
                        "INSERT INTO scan_issue(scan_id, kind, path, detail) VALUES (?, ?, ?, ?)",
                        (scan_id, kind, path, detail or None),
                    )
            ideal_total = int(
                conn.execute("SELECT count(DISTINCT image_id) FROM ideal_image WHERE verdict = 'ideal'")
                .fetchone()[0]
            )
            conn.execute(
                "UPDATE scan SET finished = ?, found = ?, probed = ?, unchanged = ?, ideal = ?, "
                "skipped = ?, issues = ?, reason = ?, result = ? WHERE id = ?",
                (
                    _now(),
                    found,
                    probed,
                    unchanged,
                    ideal_total,
                    skipped,
                    json.dumps(issue_counts),
                    reason,
                    result_state,
                    scan_id,
                ),
            )

        self._writer.submit(job).result()

    # -- helpers ----------------------------------------------------------------------------------------

    def _progress(self, scan_id: int, counters: _Counters) -> ScanProgress:
        with counters.lock:
            return ScanProgress(
                scan_id=scan_id,
                dirs=counters.dirs,
                found=counters.found,
                unchanged=counters.unchanged,
                probed=counters.probed,
                ideal=counters.ideal,
                excluded=counters.skipped,
                issues=counters.issues,
                walk_done=counters.walk_done,
                current_dir=counters.current_dir,
            )

    def _put(
        self,
        target: queue.Queue[_ResultItem | None],
        item: _ResultItem,
        cancel: CancelToken,
        abort: _Abort,
    ) -> None:
        """Blocking put that polls ``cancel`` and ``abort`` between attempts, so it NEVER blocks forever.

        On a user cancel the consumer keeps draining, so a put still lands quickly; on an abort (a failed
        writer job) the consumer is gone, so the item is dropped rather than waited on — that is what lets
        ``pool.shutdown`` and app shutdown complete when the catalogue write side has failed (§3)."""
        while True:
            if cancel.cancelled or abort.is_set():
                return  # teardown in progress: drop the item and let the worker unwind
            try:
                target.put(item, timeout=_QUEUE_POLL)
                return
            except queue.Full:
                continue


_TICK = object()  # the consumer's "batch timer expired" marker, distinct from a real item and None


def _reason_json(detection: DisplayDetection) -> str | None:
    reason = detection.reason
    if reason is None:
        return None
    return json.dumps(
        {
            "code": reason.code.value,
            "evidence": [list(pair) for pair in reason.evidence],
            "remedy": reason.remedy,
        }
    )
