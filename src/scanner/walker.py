"""The directory walk: turns a scan root into a stream of :class:`Candidate` files (concept §5, M1.5,
contract §2.7).

Two-phase scan, phase one. This module never opens a file's contents — that is :mod:`src.scanner.probe`'s
job, downstream of a bounded queue. It only ever asks the filesystem what kind of thing an entry is
(``d_type``, no ``stat``), whether the exclusion :class:`~src.scanner.exclude.Matcher` would prune it
(again, no ``stat``, no descent), and — once an entry has survived both — one ``stat`` to size it, tell a
hardlink from a new find, and tell a changed file from an unchanged one.

Everything the walk needs to be honest about the real filesystem is injected: :class:`FileSystem` (default
:class:`OsFileSystem`) stands for ``scandir``/``stat``/``lexists``, :class:`KnownFiles` stands for the
catalogue's in-memory snapshot (never imported directly — the scanner never imports the catalogue), and the
output :class:`queue.Queue` provides the only back-pressure: a full queue blocks the walker in a
0.2-second-timeout loop that polls the shared :class:`~src.util.cancel.CancelToken`, so a cancelled scan
unblocks promptly instead of hanging on a producer nobody is draining.

Per-``DirEntry`` order (ruling Q12 corrects the stale ``min_file_bytes`` in the written contract to 64 KiB):
a name that cannot be encoded back to UTF-8 is reported and skipped; the exclusion matcher is asked next,
before any ``stat`` and before any descent; a directory is entered unless it would cross a mount boundary
(D11 — a mount is its own root) or its ``(device, inode)`` has already been visited in this walk (a symlink
loop); a file is filtered by extension *before* the one ``stat`` that decides everything else. A directory
that cannot be listed is recorded in :attr:`WalkResult.failed_dirs` — nothing beneath it is ever seen, so
nothing beneath it may later be marked missing.
"""

from __future__ import annotations

import contextlib
import os
import queue
import stat
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from src.scanner.exclude import Matcher, RuleHit
from src.util.cancel import CancelToken

__all__ = [
    "DEFAULT_EXTENSIONS",
    "PUT_TIMEOUT_SECONDS",
    "Candidate",
    "FileKey",
    "FileSystem",
    "IssueKind",
    "KnownFiles",
    "OsFileSystem",
    "ScanIssue",
    "WalkListener",
    "WalkOptions",
    "WalkResult",
    "walk",
]

PUT_TIMEOUT_SECONDS = 0.2

DEFAULT_EXTENSIONS: frozenset[str] = frozenset(
    {
        "jpg",
        "jpeg",
        "jpe",
        "png",
        "webp",
        "gif",
        "bmp",
        "tif",
        "tiff",
        "avif",
        "heif",
        "heic",
        "jxl",
    }
)

FileKey = tuple[int, int, int, int]  # device, inode, mtime_ns, size


class IssueKind(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    BROKEN_SYMLINK = "broken_symlink"
    VANISHED = "vanished"
    IO_ERROR = "io_error"
    UNENCODABLE_NAME = "unencodable_name"
    SYMLINK_LOOP = "symlink_loop"
    NOT_REGULAR = "not_regular"
    OTHER_FILESYSTEM = "other_filesystem"


@dataclass(frozen=True)
class ScanIssue:
    kind: IssueKind
    path: str
    detail: str = ""


@dataclass(frozen=True)
class Candidate:
    path: str
    root: str
    key: FileKey
    moved_from_id: int | None = None


@dataclass(frozen=True)
class WalkOptions:
    """Ruling Q12: the minimum is **65536** bytes (64 KiB) — the contract's literal ``204_800`` is stale.
    ``scan.min_long_edge`` is a removable *view* filter (Q7), never dropped here."""

    extensions: frozenset[str] = DEFAULT_EXTENSIONS
    min_file_bytes: int = 65_536
    max_file_bytes: int = 268_435_456


@dataclass(frozen=True)
class WalkResult:
    complete: bool  # False only when the walk was cancelled before it finished
    failed_dirs: tuple[str, ...] = ()


class KnownFiles(Protocol):
    """The catalogue's in-memory snapshot of one root, loaded by ``ingest`` before the walk starts.

    A Protocol the walker defines for itself: ``src.scanner`` never imports ``src.catalogue``.
    """

    def key_for(self, path: str) -> FileKey | None: ...
    def by_inode(self, device: int, inode: int) -> tuple[int, str, FileKey] | None: ...  # id, old path, key


class FileSystem(Protocol):
    """Everything the walk touches on disk. ``OsFileSystem`` is the default; tests inject a double that
    counts calls or injects faults, so exclusion and hardlink/loop handling can be proven without I/O."""

    def scandir(self, path: str) -> AbstractContextManager[Iterator[os.DirEntry[str]]]: ...
    def stat(self, path: str, *, follow_symlinks: bool = True) -> os.stat_result: ...
    def lexists(self, path: str) -> bool: ...


class WalkListener(Protocol):
    def on_dir(self, path: str, candidates: int) -> None: ...
    def on_skip(self, hit: RuleHit, is_dir: bool) -> None: ...
    def on_unchanged(self, path: str) -> None: ...  # ingest bumps seen_scan without opening the file
    def on_issue(self, issue: ScanIssue) -> None: ...


class OsFileSystem:
    """The real filesystem."""

    def scandir(self, path: str) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        return os.scandir(path)

    def stat(self, path: str, *, follow_symlinks: bool = True) -> os.stat_result:
        return Path(path).stat(follow_symlinks=follow_symlinks)

    def lexists(self, path: str) -> bool:
        return os.path.lexists(path)


def _detail(exc: OSError) -> str:
    return exc.strerror or type(exc).__name__


def _extension(name: str) -> str:
    """The lower-cased extension of ``name``, or ``""`` when it has none (a leading dot is not one)."""
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return ""
    return name[dot + 1 :].lower()


def _join(dir_path: str, name: str) -> str:
    return f"/{name}" if dir_path == "/" else f"{dir_path}/{name}"


def _put(out: queue.Queue[Candidate | None], item: Candidate | None, cancel: CancelToken) -> bool:
    """Blocking put, 0.2 s at a time, polling ``cancel`` between attempts — the walk's only back-pressure.
    Returns ``False`` when cancellation wins the race before the item could be enqueued."""
    while True:
        if cancel.cancelled:
            return False
        try:
            out.put(item, timeout=PUT_TIMEOUT_SECONDS)
            return True
        except queue.Full:
            continue


def _send_end(out: queue.Queue[Candidate | None]) -> None:
    """Best-effort delivery of the end-of-walk sentinel. Unlike a candidate, this is never worth blocking
    on: once cancelled, a consumer draining the queue already knows to stop from ``cancel`` itself, and a
    still-full, undrained queue is its problem, not this call's to wait out."""
    with contextlib.suppress(queue.Full):
        out.put_nowait(None)


class _Walker:
    """Mutable state for one call to :func:`walk`. Not reentrant, not shared between threads."""

    def __init__(
        self,
        root: str,
        matcher: Matcher,
        known: KnownFiles,
        out: queue.Queue[Candidate | None],
        listener: WalkListener,
        cancel: CancelToken,
        options: WalkOptions,
        fs: FileSystem,
        stable_inodes: bool,
        root_device: int,
    ) -> None:
        self.root = root
        self.matcher = matcher
        self.known = known
        self.out = out
        self.listener = listener
        self.cancel = cancel
        self.options = options
        self.fs = fs
        self.stable_inodes = stable_inodes
        self.root_device = root_device
        self.visited_dirs: set[tuple[int, int]] = set()
        self.files_seen: set[tuple[int, int]] = set()
        self.failed_dirs: list[str] = []
        self.complete = True

    # ── driver ──

    def run(self) -> WalkResult:
        stack = [self.root]
        while stack:
            if self.cancel.cancelled:
                self.complete = False
                break
            self._visit(stack.pop(), stack)
            if not self.complete:
                break
        _send_end(self.out)  # end of walk
        return WalkResult(self.complete, tuple(self.failed_dirs))

    def _visit(self, dir_path: str, stack: list[str]) -> None:
        count = 0
        subdirs: list[str] = []
        try:
            with self.fs.scandir(dir_path) as entries:
                for entry in entries:
                    if self.cancel.cancelled:
                        self.complete = False
                        return
                    if self._entry(entry, dir_path, subdirs):
                        count += 1
                    if not self.complete:
                        return
        except OSError as exc:
            self._fail_dir(dir_path, exc)
            return
        self.listener.on_dir(dir_path, count)
        stack.extend(reversed(subdirs))

    # ── one entry ──

    def _entry(self, entry: os.DirEntry[str], dir_path: str, subdirs: list[str]) -> bool:
        name = entry.name
        path = _join(dir_path, name)
        try:
            name.encode("utf-8")
        except UnicodeEncodeError:
            self._issue(IssueKind.UNENCODABLE_NAME, path, "name is not UTF-8-encodable")
            return False

        is_dir_hint = entry.is_dir(follow_symlinks=False)  # d_type only
        is_symlink = entry.is_symlink()  # d_type only

        hit = self.matcher.match(path, is_dir_hint)
        if hit is not None:
            self.listener.on_skip(hit, is_dir_hint)
            return False

        try:
            inode = entry.inode()
        except OSError:
            inode = None
        if inode is not None:
            inode_hit = self.matcher.match_inode(self.root_device, inode)
            if inode_hit is not None:
                self.listener.on_skip(inode_hit, is_dir_hint)
                return False

        if is_dir_hint:
            self._enter_dir(path, None, subdirs)
            return False
        if is_symlink:
            return self._symlink(path, name, subdirs)
        return self._file(path, name, None)

    def _symlink(self, path: str, name: str, subdirs: list[str]) -> bool:
        try:
            st = self.fs.stat(path, follow_symlinks=True)
        except OSError as exc:
            self._issue(IssueKind.BROKEN_SYMLINK, path, _detail(exc))
            return False
        if stat.S_ISDIR(st.st_mode):
            self._enter_dir(path, st, subdirs)
            return False
        if stat.S_ISREG(st.st_mode):
            return self._file(path, name, st)
        self._issue(IssueKind.NOT_REGULAR, path)
        return False

    def _enter_dir(self, path: str, prefetched: os.stat_result | None, subdirs: list[str]) -> None:
        st = prefetched
        if st is None:
            try:
                st = self.fs.stat(path, follow_symlinks=True)
            except OSError as exc:
                self._fail_dir(path, exc)
                return
        # Descending never leaves the device the root started on: every directory reached from here has
        # already passed this check, so `root_device` is also *this* directory's device (D11).
        if st.st_dev != self.root_device:
            self._issue(IssueKind.OTHER_FILESYSTEM, path)
            return
        key = (st.st_dev, st.st_ino)
        if key in self.visited_dirs:
            self._issue(IssueKind.SYMLINK_LOOP, path)
            return
        self.visited_dirs.add(key)
        subdirs.append(path)

    def _file(self, path: str, name: str, prefetched: os.stat_result | None) -> bool:
        if _extension(name) not in self.options.extensions:
            return False
        st = prefetched
        if st is None:
            try:
                st = self.fs.stat(path, follow_symlinks=True)
            except FileNotFoundError:
                self._issue(IssueKind.VANISHED, path)
                return False
            except PermissionError as exc:
                self._issue(IssueKind.PERMISSION_DENIED, path, _detail(exc))
                return False
            except OSError as exc:
                self._issue(IssueKind.IO_ERROR, path, _detail(exc))
                return False
        if not stat.S_ISREG(st.st_mode):
            self._issue(IssueKind.NOT_REGULAR, path)
            return False
        if not (self.options.min_file_bytes <= st.st_size <= self.options.max_file_bytes):
            return False
        ident = (st.st_dev, st.st_ino)
        if ident in self.files_seen:
            return False  # a hardlink or bind mount already produced a candidate this scan
        self.files_seen.add(ident)

        key: FileKey = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
        if self.known.key_for(path) == key:
            self.listener.on_unchanged(path)
            return False

        moved_from_id: int | None = None
        if self.stable_inodes:
            moved = self.known.by_inode(st.st_dev, st.st_ino)
            if moved is not None:
                old_id, old_path, old_key = moved
                if (
                    old_key[2] == key[2]
                    and old_key[3] == key[3]
                    and old_path != path
                    and not self.fs.lexists(old_path)
                ):
                    moved_from_id = old_id

        candidate = Candidate(path=path, root=self.root, key=key, moved_from_id=moved_from_id)
        if not _put(self.out, candidate, self.cancel):
            self.complete = False
            return False
        return True

    # ── issues ──

    def _issue(self, kind: IssueKind, path: str, detail: str = "") -> None:
        self.listener.on_issue(ScanIssue(kind, path, detail))

    def _fail_dir(self, path: str, exc: OSError) -> None:
        kind = IssueKind.PERMISSION_DENIED if isinstance(exc, PermissionError) else IssueKind.IO_ERROR
        self._issue(kind, path, _detail(exc))
        self.failed_dirs.append(path)


_DEFAULT_OPTIONS = WalkOptions()
_DEFAULT_FS = OsFileSystem()


def walk(
    root: str,
    matcher: Matcher,
    known: KnownFiles,
    out: queue.Queue[Candidate | None],
    listener: WalkListener,
    cancel: CancelToken,
    options: WalkOptions = _DEFAULT_OPTIONS,
    fs: FileSystem = _DEFAULT_FS,
    stable_inodes: bool = True,
) -> WalkResult:
    """Walk ``root``, putting a :class:`Candidate` on ``out`` for every new or changed file, ``None`` last.

    Never raises: a ``root`` that cannot even be ``stat``ed or is not a directory becomes its own
    ``failed_dirs`` entry with ``complete=True`` (the walk was not cancelled, it simply found nothing to
    walk); only cancellation before completion makes ``complete`` ``False``.
    """
    root = "/" + root.strip("/")
    try:
        root_stat = fs.stat(root, follow_symlinks=True)
    except OSError as exc:
        kind = IssueKind.PERMISSION_DENIED if isinstance(exc, PermissionError) else IssueKind.IO_ERROR
        listener.on_issue(ScanIssue(kind, root, _detail(exc)))
        _send_end(out)
        return WalkResult(not cancel.cancelled, (root,))
    if not stat.S_ISDIR(root_stat.st_mode):
        listener.on_issue(ScanIssue(IssueKind.NOT_REGULAR, root, "root is not a directory"))
        _send_end(out)
        return WalkResult(not cancel.cancelled, (root,))

    walker = _Walker(
        root, matcher, known, out, listener, cancel, options, fs, stable_inodes, root_stat.st_dev
    )
    walker.visited_dirs.add((root_stat.st_dev, root_stat.st_ino))
    return walker.run()
