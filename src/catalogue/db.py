"""The SQLite catalogue: connections, migrations, rules, exclusion flags, display snapshots, settings.

Connection policy (M1 contract §2.4 / §3)
    ``isolation_level=None`` and explicit ``BEGIN IMMEDIATE`` for writes (:func:`transaction`);
    ``journal_mode=WAL``, ``synchronous=NORMAL``, ``foreign_keys=ON``, busy timeout 5 s, ``sqlite3.Row``.
    Read connections add ``query_only=ON`` and are one per thread (:class:`ReadConnections`); ``sqlite3``'s
    own same-thread check stays on, so a connection that leaks to another thread fails loudly. A process
    has exactly one write connection, owned by the writer thread (``ingest.CatalogueWriter``, P5): every
    mutating function here takes that connection and joins the writer's open transaction.

Errors are typed and never destructive: a database that is too new, busy, corrupt or unreachable is
reported and left byte-for-byte as it was. Every SQL value is a bound parameter.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from src.catalogue.migrations import MIGRATIONS, Migration
from src.catalogue.model import FlagDelta, RulePreview
from src.config import config_paths
from src.scanner.displays import DisplayDetection
from src.scanner.exclude import (
    BUILTIN_GROUPS,
    BuiltinGroup,
    Group,
    Matcher,
    Rule,
    RuleHit,
    RuleKind,
    validate_rule,
)

T = TypeVar("T")

_LOG = logging.getLogger(__name__)

LATEST_SCHEMA = 1
BUSY_TIMEOUT_MS = 5000
PREVIEW_SAMPLE = 5

DEFAULT_SETTINGS: dict[str, object] = {
    "scan.min_file_bytes": 65_536,  # ruling Q6
    "scan.max_file_bytes": 268_435_456,
    "scan.min_long_edge": 1280,  # ruling Q7: a default, removable VIEW filter — rows are stored regardless
    "ideal.threshold_pct": 16,  # ruling Q1
    "thumbs.budget_bytes": 536_870_912,
    "scan.network_optin": [],
    "first_run_done": False,
}


# ── errors ───────────────────────────────────────────────────────────────────────────────────────────────


class CatalogueError(Exception):
    """Base class of every catalogue failure."""


class SchemaTooNewError(CatalogueError):
    """The file was written by a newer release. It is never modified."""

    def __init__(self, found: int, supported: int) -> None:
        super().__init__(f"catalogue schema version {found} is newer than the supported version {supported}")
        self.found = found
        self.supported = supported


class CatalogueBusyError(CatalogueError):
    """Another connection held the write lock for longer than the busy timeout."""


class CatalogueCorruptError(CatalogueError):
    """The file is not a usable SQLite database. It is never deleted or repaired automatically."""


class CatalogueUnavailableError(CatalogueError):
    """The file cannot be opened or written at all (a directory in its place, a read-only location…)."""


class ScanInProgressError(CatalogueError):
    def __init__(self, pid: int | None) -> None:
        super().__init__("another scan is running" + ("" if pid is None else f" (pid {pid})"))
        self.pid = pid


def translate_error(error: sqlite3.Error) -> CatalogueError:
    """Map a ``sqlite3`` exception onto the typed catalogue errors."""
    text = str(error)
    lowered = text.lower()
    if isinstance(error, sqlite3.OperationalError):
        if "locked" in lowered or "busy" in lowered:
            return CatalogueBusyError(text)
        if "unable to open" in lowered or "readonly" in lowered or "read-only" in lowered:
            return CatalogueUnavailableError(text)
        if "malformed" in lowered or "corrupt" in lowered:
            return CatalogueCorruptError(text)
        return CatalogueError(text)
    if isinstance(error, sqlite3.IntegrityError):
        return CatalogueError(text)
    if isinstance(error, sqlite3.DatabaseError):  # "file is not a database", "disk image is malformed"
        return CatalogueCorruptError(text)
    return CatalogueError(text)


@contextlib.contextmanager
def _typed_errors() -> Iterator[None]:
    try:
        yield
    except sqlite3.Error as error:
        raise translate_error(error) from error


# ── connections and transactions ─────────────────────────────────────────────────────────────────────────


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open one connection under the connection policy. A schema that is too new is refused untouched."""
    target = Path(path)
    uri = target.absolute().as_uri() + ("?mode=rw" if readonly else "?mode=rwc")
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    except sqlite3.Error as error:
        raise translate_error(error) from error
    try:
        conn.row_factory = sqlite3.Row
        found = int(conn.execute("PRAGMA user_version").fetchone()[0])  # first read: garbage fails here
        if found > LATEST_SCHEMA:
            raise SchemaTooNewError(found, LATEST_SCHEMA)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        if not readonly:
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        if readonly:
            conn.execute("PRAGMA query_only = ON")
    except sqlite3.Error as error:
        conn.close()
        raise translate_error(error) from error
    except CatalogueError:
        conn.close()
        raise
    return conn


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT``; rolls back on any exception. Joins a transaction already open.

    The writer thread wraps each submitted job in one transaction; functions in this package use this
    context manager too, so they work both inside such a job and on their own.
    """
    if conn.in_transaction:
        with _typed_errors():
            yield conn
        return
    with _typed_errors():
        conn.execute("BEGIN IMMEDIATE")
    try:
        with _typed_errors():
            yield conn
            conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
        raise


class ReadConnections:
    """One ``query_only`` connection per thread, opened lazily and never shared (contract §3).

    ``sqlite3`` refuses to use — or close — a connection from another thread, so each worker closes its own
    with ``close_current()``; ``close()`` only stops new connections from being opened.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._local = threading.local()
        self._closed = threading.Event()

    def get(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            if self._closed.is_set():
                raise CatalogueError("read connections are closed")
            conn = connect(self._path, readonly=True)
            self._local.conn = conn
        return conn

    def close_current(self) -> None:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            self._local.conn = None
            conn.close()

    def close(self) -> None:
        self._closed.set()
        self.close_current()


def database_path(conn: sqlite3.Connection) -> Path | None:
    """The main database file of ``conn``; ``None`` for an in-memory database."""
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return Path(row[2]) if row[2] else None
    return None


# ── migrations ───────────────────────────────────────────────────────────────────────────────────────────


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    # PRAGMA takes no bound parameters. The only formatted statement in the package: a checked int.
    if type(version) is not int or not 0 < version < 100_000:
        raise ValueError(f"bad schema version: {version!r}")
    statement = "PRAGMA user_version = " + str(version)
    conn.execute(statement)


def _backup(conn: sqlite3.Connection, version: int) -> Path | None:
    source = database_path(conn)
    if source is None:
        return None
    final = source.with_name(f"{source.name}.bak-v{version}")
    partial = source.with_name(f"{source.name}.bak-v{version}.tmp")
    partial.unlink(missing_ok=True)
    copy = sqlite3.connect(partial)
    try:
        conn.backup(copy)
    finally:
        copy.close()
    partial.chmod(0o600)
    partial.replace(final)
    return final


def run_migrations(conn: sqlite3.Connection, migrations: Sequence[Migration]) -> int:
    """Bring ``conn`` up to the last of ``migrations``. Idempotent; each step is one transaction."""
    latest = migrations[-1].version if migrations else 0
    with _typed_errors():
        current = _user_version(conn)
    if current > latest:
        raise SchemaTooNewError(current, latest)
    if current == latest:
        return current
    if current >= 1:
        try:
            _backup(conn, current)
        except (OSError, sqlite3.Error) as error:
            raise CatalogueError(f"could not back the catalogue up before migrating: {error}") from error
    for step in migrations:
        if step.version <= current:
            continue
        with transaction(conn):
            if _user_version(conn) >= step.version:  # another process migrated while we waited for the lock
                continue
            step.apply(conn)
            _set_user_version(conn, step.version)
        _LOG.info("catalogue migrated to schema %d (%s)", step.version, step.name)
    with _typed_errors():
        return _user_version(conn)


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every pending migration and return the new ``user_version``."""
    return run_migrations(conn, MIGRATIONS)


# ── open / recover / scan lock ───────────────────────────────────────────────────────────────────────────


def _precreate(path: Path) -> None:
    """Make the directory 0700 and the file 0600 (the catalogue lists the user's private paths)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600))
    except FileExistsError:
        return
    except OSError as error:
        raise CatalogueUnavailableError(f"cannot create the catalogue at {path}: {error}") from error


def open_catalogue(path: Path | None = None) -> sqlite3.Connection:
    """mkdir 0700 → connect → migrate → seed the built-in exclusion groups → recover interrupted scans."""
    target = Path(path) if path is not None else config_paths.catalogue_db()
    _precreate(target)
    conn = connect(target)
    try:
        migrate(conn)
        seed_builtins(conn, BUILTIN_GROUPS)
        recover(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _lock_path(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".scanlock")


def _scan_running(db_path: Path) -> bool:
    """True when another process (or thread) holds the scan lock right now."""
    try:
        fd = os.open(_lock_path(db_path), os.O_RDWR | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def recover(conn: sqlite3.Connection) -> int:
    """Mark scans that never finished as ``interrupted`` — unless a live scanner holds the scan lock."""
    with _typed_errors():
        pending = conn.execute(
            "SELECT count(*) FROM scan WHERE finished IS NULL AND result = 'running'"
        ).fetchone()[0]
    if not pending:
        return 0
    path = database_path(conn)
    if path is not None and _scan_running(path):
        return 0
    with transaction(conn):
        cursor = conn.execute(
            "UPDATE scan SET result = 'interrupted' WHERE finished IS NULL AND result = 'running'"
        )
        return int(cursor.rowcount)


@contextlib.contextmanager
def scan_lock(db_path: Path) -> Iterator[None]:
    """Non-blocking exclusive ``flock`` on ``<db>.scanlock``; dies with the process. One scanner only."""
    lock_file = _lock_path(Path(db_path))
    try:
        fd = os.open(lock_file, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except OSError as error:
        raise CatalogueUnavailableError(f"cannot create {lock_file}: {error}") from error
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raw = os.pread(fd, 32, 0).decode("ascii", "replace").strip()
            raise ScanInProgressError(int(raw) if raw.isdigit() else None) from error
        os.ftruncate(fd, 0)
        os.pwrite(fd, str(os.getpid()).encode("ascii"), 0)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ── exclusion rules and groups ───────────────────────────────────────────────────────────────────────────


def seed_builtins(conn: sqlite3.Connection, groups: Sequence[BuiltinGroup]) -> None:
    """Upsert the built-in groups by ``key`` and their rules by ``(kind, value)``. Idempotent; the user's
    ``enabled`` toggles survive (a locked group is always on). Writes nothing when nothing changed."""
    with _typed_errors():
        if not _seed_needed(conn, groups):
            return
    with transaction(conn):
        for group in groups:
            locked = int(group.locked)
            conn.execute(
                "INSERT INTO exclusion_group(key, name, builtin, locked, enabled) VALUES (?, ?, 1, ?, 1) "
                "ON CONFLICT(key) DO UPDATE SET name = excluded.name, builtin = 1, locked = excluded.locked, "
                "enabled = CASE WHEN excluded.locked = 1 THEN 1 ELSE exclusion_group.enabled END",
                (group.key, group.name, locked),
            )
            group_id = conn.execute("SELECT id FROM exclusion_group WHERE key = ?", (group.key,)).fetchone()[
                0
            ]
            wanted = {(kind.value, value) for kind, value in group.rules}
            for row in conn.execute(
                "SELECT id, kind, value FROM exclusion WHERE builtin = 1 AND group_id = ?", (group_id,)
            ).fetchall():
                if (row["kind"], row["value"]) not in wanted:  # dropped from the table by a newer release
                    conn.execute("DELETE FROM exclusion WHERE id = ?", (row["id"],))
            for kind, value in group.rules:
                conn.execute(
                    "INSERT INTO exclusion(kind, value, group_id, builtin, enabled) VALUES (?, ?, ?, 1, 1) "
                    "ON CONFLICT(kind, value, ifnull(volume_id,''), ifnull(root_id,0)) DO UPDATE SET "
                    "builtin = 1, group_id = excluded.group_id, "
                    "enabled = CASE WHEN ? = 1 THEN 1 ELSE exclusion.enabled END",
                    (kind.value, value, group_id, locked),
                )


def _seed_needed(conn: sqlite3.Connection, groups: Sequence[BuiltinGroup]) -> bool:
    stored = {
        row["key"]: row
        for row in conn.execute(
            "SELECT id, key, name, locked, enabled FROM exclusion_group WHERE builtin = 1 AND key IS NOT NULL"
        )
    }
    for group in groups:
        row = stored.get(group.key)
        if row is None or row["name"] != group.name or bool(row["locked"]) != group.locked:
            return True
        if group.locked and not row["enabled"]:
            return True
        rules = conn.execute(
            "SELECT kind, value, enabled FROM exclusion WHERE builtin = 1 AND group_id = ? "
            "AND volume_id IS NULL AND root_id IS NULL",
            (row["id"],),
        ).fetchall()
        if {(r["kind"], r["value"]) for r in rules} != {(kind.value, value) for kind, value in group.rules}:
            return True
        if group.locked and any(not r["enabled"] for r in rules):
            return True
    return False


def load_rules(conn: sqlite3.Connection) -> tuple[list[Rule], list[Group]]:
    """Every rule and group as the pure records ``scanner.exclude.compile_matcher`` takes."""
    with _typed_errors():
        groups = [
            Group(
                id=row["id"],
                key=row["key"] or "",
                name=row["name"],
                builtin=bool(row["builtin"]),
                locked=bool(row["locked"]),
                enabled=bool(row["enabled"]),
            )
            for row in conn.execute(
                "SELECT id, key, name, builtin, locked, enabled FROM exclusion_group ORDER BY id"
            )
        ]
        rules = [
            Rule(
                id=row["id"],
                kind=RuleKind(row["kind"]),
                value=row["value"],
                group_id=row["group_id"],
                root=row["root_path"],
                volume_id=row["volume_id"],
                device=row["device"],
                inode=row["inode"],
                enabled=bool(row["enabled"]),
            )
            for row in conn.execute(
                "SELECT e.id, e.kind, e.value, e.group_id, r.path AS root_path, e.volume_id, e.device, "
                "e.inode, e.enabled FROM exclusion e LEFT JOIN root r ON r.id = e.root_id ORDER BY e.id"
            )
        ]
    return rules, groups


def _group_row(conn: sqlite3.Connection, name_or_key: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT id, key, name, builtin, locked, enabled FROM exclusion_group WHERE key = ? OR name = ? "
        "ORDER BY (key = ?) DESC LIMIT 1",
        (name_or_key, name_or_key, name_or_key),
    ).fetchone()
    return row


def add_rule(
    conn: sqlite3.Connection,
    kind: RuleKind,
    value: str,
    *,
    group: str | None,
    root: str | None,
    volume_id: str | None = None,
    device: int | None = None,
    inode: int | None = None,
    now: int | None = None,
    note: str | None = None,
) -> int:
    """Add a user rule and return its id (the existing id when the same rule is already stored).

    ``value`` is validated by ``scanner.exclude.validate_rule`` (raises ``PatternError``). ``group`` names a
    group by key or name and is created as a user group when unknown; a locked group takes no user rules.
    ``root`` must be the path of a stored root. ``device``/``inode`` are kept for FILE rules only.
    """
    rule_kind = RuleKind(kind)
    validate_rule(rule_kind, value, volume_relative=volume_id is not None)
    if rule_kind is not RuleKind.FILE:
        device = inode = None
    with transaction(conn):
        root_id: int | None = None
        if root is not None:
            found = conn.execute("SELECT id FROM root WHERE path = ?", (root,)).fetchone()
            if found is None:
                raise CatalogueError(f"not a scan root: {root!r}")
            root_id = int(found[0])
        group_id: int | None = None
        if group is not None:
            if not group.strip():
                raise CatalogueError("group name is empty")
            row = _group_row(conn, group)
            if row is None:
                group_id = int(
                    conn.execute("INSERT INTO exclusion_group(name) VALUES (?)", (group,)).lastrowid or 0
                )
            elif row["locked"]:
                raise CatalogueError(f"group {row['name']!r} is locked")
            else:
                group_id = int(row["id"])
        existing = conn.execute(
            "SELECT id FROM exclusion WHERE kind = ? AND value = ? AND ifnull(volume_id,'') = ifnull(?,'') "
            "AND ifnull(root_id,0) = ifnull(?,0)",
            (rule_kind.value, value, volume_id, root_id),
        ).fetchone()
        if existing is not None:
            return int(existing[0])
        cursor = conn.execute(
            "INSERT INTO exclusion(kind, value, volume_id, device, inode, root_id, group_id, builtin, "
            "enabled, created, note) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)",
            (rule_kind.value, value, volume_id, device, inode, root_id, group_id, now, note),
        )
        return int(cursor.lastrowid or 0)


def _rule_guard(conn: sqlite3.Connection, rule_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT e.id, e.builtin, ifnull(g.locked, 0) AS locked FROM exclusion e "
        "LEFT JOIN exclusion_group g ON g.id = e.group_id WHERE e.id = ?",
        (rule_id,),
    ).fetchone()
    if row is None:
        raise CatalogueError(f"no exclusion rule with id {rule_id}")
    return row


def remove_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    """Delete a user rule. Built-in rules can only be switched off. Flags pointing at it become NULL
    (``ON DELETE SET NULL``); run ``apply_exclusions`` afterwards so overlapping rules take over."""
    with transaction(conn):
        if _rule_guard(conn, rule_id)["builtin"]:
            raise CatalogueError("a built-in rule cannot be removed, only disabled")
        conn.execute("DELETE FROM exclusion WHERE id = ?", (rule_id,))


def set_rule_enabled(conn: sqlite3.Connection, rule_id: int, on: bool) -> None:
    with transaction(conn):
        if _rule_guard(conn, rule_id)["locked"] and not on:
            raise CatalogueError("a rule of a locked group cannot be disabled")
        conn.execute("UPDATE exclusion SET enabled = ? WHERE id = ?", (int(bool(on)), rule_id))


def set_group_enabled(conn: sqlite3.Connection, name_or_key: str, on: bool) -> None:
    with transaction(conn):
        row = _group_row(conn, name_or_key)
        if row is None:
            raise CatalogueError(f"no exclusion group named {name_or_key!r}")
        if row["locked"]:
            raise CatalogueError(f"group {row['name']!r} is locked")
        conn.execute("UPDATE exclusion_group SET enabled = ? WHERE id = ?", (int(bool(on)), row["id"]))


def _hit_for(matcher: Matcher, path: str, device: int | None, inode: int | None) -> RuleHit | None:
    """The winning rule for one catalogue row: by path (every ancestor), then by inode for renamed files."""
    try:
        hit = matcher.match_path(path)
    except ValueError:  # a stored path the matcher refuses (not absolute): hostile data, not an exclusion
        hit = None
    if (hit is None or hit.kind is not RuleKind.FILE) and device is not None and inode is not None:
        by_inode = matcher.match_inode(device, inode)
        if by_inode is not None:
            return by_inode
    return hit


def apply_exclusions(conn: sqlite3.Connection, matcher: Matcher) -> FlagDelta:
    """Recompute ``image.excluded_by`` for ALL rows (D8). Rows are never deleted and no other column is
    touched, so re-including restores an image instantly with its data intact."""
    flagged = cleared = 0
    updates: list[tuple[int | None, int]] = []
    with transaction(conn):
        for row in conn.execute("SELECT id, path, device, inode, excluded_by FROM image"):
            hit = _hit_for(matcher, row["path"], row["device"], row["inode"])
            wanted = None if hit is None else hit.rule_id
            current = row["excluded_by"]
            if wanted == current:
                continue
            if current is None:
                flagged += 1
            elif wanted is None:
                cleared += 1
            updates.append((wanted, row["id"]))
        conn.executemany("UPDATE image SET excluded_by = ? WHERE id = ?", updates)
    return FlagDelta(flagged=flagged, cleared=cleared)


def preview_rule(conn: sqlite3.Connection, matcher_with_candidate: Matcher, rule_id: int) -> RulePreview:
    """How many catalogued images the candidate rule ``rule_id`` would exclude. Read-only.

    Counts rows that are visible now (not already excluded) and whose winning rule under the candidate
    matcher is ``rule_id`` — the number of images that would actually leave Browse.
    """
    images = 0
    folders: set[str] = set()
    sample: list[str] = []
    with _typed_errors():
        rows = conn.execute(
            "SELECT path, dir, device, inode FROM image WHERE excluded_by IS NULL ORDER BY path"
        )
        for row in rows:
            hit = _hit_for(matcher_with_candidate, row["path"], row["device"], row["inode"])
            if hit is None or hit.rule_id != rule_id:
                continue
            images += 1
            folders.add(row["dir"])
            if len(sample) < PREVIEW_SAMPLE:
                sample.append(row["path"])
    return RulePreview(rule_id=rule_id, images=images, folders=len(folders), sample_paths=tuple(sample))


# ── displays ─────────────────────────────────────────────────────────────────────────────────────────────


def target_display_ids(conn: sqlite3.Connection) -> list[int]:
    """Ids of the current target displays (``connected = 1``: detected and declared alike), in id order."""
    with _typed_errors():
        return [int(row[0]) for row in conn.execute("SELECT id FROM display WHERE connected = 1 ORDER BY id")]


def save_display_snapshot(
    conn: sqlite3.Connection, detection: DisplayDetection, now: int
) -> tuple[list[int], bool]:
    """Persist ``detection.displays`` as THE target set and return ``(target ids, changed?)``.

    Every display in the detection — declared ones included (ruling Q3) — gets ``connected = 1``; every
    other stored display gets ``connected = 0`` and stops being a target. ``changed`` tells the caller to
    run ``ideal.rebuild``. An empty detection therefore empties the target set: callers that want to keep
    the last known displays when detection fails must not save the empty snapshot.
    """
    with transaction(conn):
        before = target_display_ids(conn)
        conn.execute("UPDATE display SET connected = 0 WHERE connected <> 0")
        for display in detection.displays:
            conn.execute(
                "INSERT INTO display(name, width, height, scale, is_primary, source, connected, first_seen, "
                "last_seen) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(name, width, height) DO UPDATE SET scale = excluded.scale, "
                "is_primary = excluded.is_primary, source = excluded.source, connected = 1, "
                "last_seen = excluded.last_seen",
                (
                    display.name,
                    int(display.width),
                    int(display.height),
                    float(display.scale),
                    int(bool(display.primary)),
                    str(display.source.value),
                    now,
                    now,
                ),
            )
        after = target_display_ids(conn)
    return after, before != after


# ── settings ─────────────────────────────────────────────────────────────────────────────────────────────


def get_setting(conn: sqlite3.Connection, key: str, default: T) -> T:
    """The stored JSON value; ``default`` when absent, unparseable or of another type than ``default``."""
    with _typed_errors():
        row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError):
        return default
    if default is not None and type(value) is not type(default):
        return default
    stored: T = value
    return stored


def set_setting(conn: sqlite3.Connection, key: str, value: object) -> None:
    text = json.dumps(value, allow_nan=False, sort_keys=True)
    with transaction(conn):
        conn.execute(
            "INSERT INTO setting(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, text),
        )


# ── change feed ──────────────────────────────────────────────────────────────────────────────────────────


class ChangeKind(StrEnum):
    IMAGES_UPSERTED = "images_upserted"
    IMAGES_FLAGGED = "images_flagged"
    IDEAL_REBUILT = "ideal_rebuilt"
    DISPLAYS_CHANGED = "displays_changed"
    ROOTS_CHANGED = "roots_changed"
    RULES_CHANGED = "rules_changed"


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    image_ids: tuple[int, ...] = ()
    scan_id: int | None = None


class ChangeFeed:
    """Thread-safe fan-out of committed changes. Callbacks run on the emitting (writer) thread and must
    hand off to their own scheduler; one that raises is logged and does not stop the others."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, Callable[[Change], None]] = {}
        self._next = 0

    def subscribe(self, cb: Callable[[Change], None]) -> Callable[[], None]:
        with self._lock:
            token = self._next
            self._next += 1
            self._subscribers[token] = cb

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.pop(token, None)

        return unsubscribe

    def emit(self, c: Change) -> None:
        with self._lock:
            callbacks = list(self._subscribers.values())
        for callback in callbacks:
            try:
                callback(c)
            except Exception:
                _LOG.exception("change-feed subscriber failed")
