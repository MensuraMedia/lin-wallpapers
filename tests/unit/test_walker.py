"""scanner/walker.py — the directory walk (contract §2.7, ruling Q12: 64 KiB minimum).

Every test walks a real ``tmp_path`` tree (real ``scandir``/``stat`` semantics, symlinks, permissions,
FIFOs), with a :class:`CountingFs` wrapper so a test can assert an excluded subtree is never even looked
at, and fake :class:`KnownFiles`/:class:`WalkListener` doubles so move detection and issue reporting can be
asserted precisely without a catalogue.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path

from src.scanner.exclude import Group, Matcher, Rule, RuleHit, RuleKind, compile_matcher
from src.scanner.walker import (
    Candidate,
    FileKey,
    IssueKind,
    ScanIssue,
    WalkOptions,
    WalkResult,
    walk,
)
from src.util.cancel import CancelToken

HOME = "/home/u"


# ── test doubles ─────────────────────────────────────────────────────────────────────────────────────────


class CountingFs:
    """The real filesystem, with every call recorded and optional injected faults/overrides."""

    def __init__(self) -> None:
        self.scandir_calls: list[str] = []
        self.stat_calls: list[str] = []
        self.lexists_calls: list[str] = []
        self.scandir_errors: dict[str, OSError] = {}
        self.stat_errors: dict[str, OSError] = {}
        self.dev_overrides: dict[str, int] = {}
        self.lexists_overrides: dict[str, bool] = {}

    def scandir(self, path: str) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        self.scandir_calls.append(path)
        if path in self.scandir_errors:
            raise self.scandir_errors[path]
        return os.scandir(path)

    def stat(self, path: str, *, follow_symlinks: bool = True) -> os.stat_result:
        self.stat_calls.append(path)
        if path in self.stat_errors:
            raise self.stat_errors[path]
        real = Path(path).stat(follow_symlinks=follow_symlinks)
        if path in self.dev_overrides:
            return _FakeStat(real, self.dev_overrides[path])
        return real

    def lexists(self, path: str) -> bool:
        self.lexists_calls.append(path)
        if path in self.lexists_overrides:
            return self.lexists_overrides[path]
        return os.path.lexists(path)


class _FakeStat:
    """A stand-in for ``os.stat_result`` with one field overridden; the walker reads no others."""

    def __init__(self, real: os.stat_result, dev: int) -> None:
        self.st_dev = dev
        self.st_ino = real.st_ino
        self.st_mode = real.st_mode
        self.st_size = real.st_size
        self.st_mtime_ns = real.st_mtime_ns


class FakeKnown:
    def __init__(
        self,
        keys: dict[str, FileKey] | None = None,
        by_inode_map: dict[tuple[int, int], tuple[int, str, FileKey]] | None = None,
    ) -> None:
        self._keys = keys or {}
        self._by_inode = by_inode_map or {}
        self.key_for_calls: list[str] = []
        self.by_inode_calls: list[tuple[int, int]] = []

    def key_for(self, path: str) -> FileKey | None:
        self.key_for_calls.append(path)
        return self._keys.get(path)

    def by_inode(self, device: int, inode: int) -> tuple[int, str, FileKey] | None:
        self.by_inode_calls.append((device, inode))
        return self._by_inode.get((device, inode))


class RecordingListener:
    def __init__(self) -> None:
        self.dirs: list[tuple[str, int]] = []
        self.skips: list[tuple[RuleHit, bool]] = []
        self.unchanged: list[str] = []
        self.issues: list[ScanIssue] = []

    def on_dir(self, path: str, candidates: int) -> None:
        self.dirs.append((path, candidates))

    def on_skip(self, hit: RuleHit, is_dir: bool) -> None:
        self.skips.append((hit, is_dir))

    def on_unchanged(self, path: str) -> None:
        self.unchanged.append(path)

    def on_issue(self, issue: ScanIssue) -> None:
        self.issues.append(issue)

    def issue_kinds(self) -> list[IssueKind]:
        return [issue.kind for issue in self.issues]


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────


def _matcher(rules: Iterable[Rule] = (), groups: Iterable[Group] = (), *, home: str = HOME) -> Matcher:
    return compile_matcher(rules, groups, home=home)


def _drain(q: queue.Queue[Candidate | None]) -> list[Candidate]:
    items: list[Candidate] = []
    while True:
        item = q.get_nowait()
        if item is None:
            return items
        items.append(item)


def _run(
    root: Path,
    matcher: Matcher,
    known: FakeKnown | None = None,
    listener: RecordingListener | None = None,
    fs: CountingFs | None = None,
    options: WalkOptions | None = None,
    stable_inodes: bool = True,
    cancel: CancelToken | None = None,
) -> tuple[WalkResult, list[Candidate], RecordingListener, CountingFs]:
    known = known if known is not None else FakeKnown()
    listener = listener if listener is not None else RecordingListener()
    fs = fs if fs is not None else CountingFs()
    options = options if options is not None else WalkOptions(min_file_bytes=0)
    cancel = cancel if cancel is not None else CancelToken()
    out: queue.Queue[Candidate | None] = queue.Queue()
    result = walk(str(root), matcher, known, out, listener, cancel, options, fs, stable_inodes)
    candidates = _drain(out)
    return result, candidates, listener, fs


# ── exclusion never touches the filesystem ──────────────────────────────────────────────────────────────


def test_excluded_dir_is_never_scandired_or_stated(tmp_path: Path) -> None:
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)
    skip = tmp_path / "skip"
    skip.mkdir()
    (skip / "a.jpg").write_bytes(b"x" * 100)
    nested = skip / "nested"
    nested.mkdir()
    (nested / "z.jpg").write_bytes(b"x" * 100)

    matcher = _matcher([Rule(1, RuleKind.FOLDER, str(skip))])
    result, candidates, listener, fs = _run(tmp_path, matcher)

    assert result.complete
    assert [c.path for c in candidates] == [str(tmp_path / "keep.jpg")]
    assert len(listener.skips) == 1
    assert listener.skips[0][0].rule_id == 1
    assert listener.skips[0][1] is True  # is_dir
    assert not any(call == str(skip) or call.startswith(str(skip) + "/") for call in fs.scandir_calls)
    assert not any(call == str(skip) or call.startswith(str(skip) + "/") for call in fs.stat_calls)


def test_excluded_file_is_never_stated(tmp_path: Path) -> None:
    keep = tmp_path / "keep.jpg"
    keep.write_bytes(b"x" * 100)
    skip = tmp_path / "secret.jpg"
    skip.write_bytes(b"x" * 100)

    matcher = _matcher([Rule(1, RuleKind.FILE, str(skip))])
    result, candidates, _listener, fs = _run(tmp_path, matcher)

    assert result.complete
    assert [c.path for c in candidates] == [str(keep)]
    assert str(skip) not in fs.stat_calls


# ── unchanged / changed ──────────────────────────────────────────────────────────────────────────────────


def test_unchanged_file_yields_no_candidate_and_a_single_lookup(tmp_path: Path) -> None:
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"x" * 100)
    st = path.stat()
    key: FileKey = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
    known = FakeKnown(keys={str(path): key})

    result, candidates, listener, fs = _run(tmp_path, _matcher(), known=known)

    assert result.complete
    assert candidates == []
    assert listener.unchanged == [str(path)]
    assert known.key_for_calls == [str(path)]
    assert known.by_inode_calls == []  # never reached: key matched first
    assert fs.lexists_calls == []


def test_changed_mtime_or_size_yields_a_candidate(tmp_path: Path) -> None:
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"x" * 100)
    st = path.stat()
    stale_key: FileKey = (st.st_dev, st.st_ino, st.st_mtime_ns - 1, st.st_size)
    known = FakeKnown(keys={str(path): stale_key})

    _result, candidates, listener, _fs = _run(tmp_path, _matcher(), known=known)

    assert len(candidates) == 1
    assert candidates[0].path == str(path)
    assert candidates[0].key == (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
    assert candidates[0].moved_from_id is None
    assert listener.unchanged == []


def test_new_file_with_no_known_row_is_a_plain_candidate(tmp_path: Path) -> None:
    path = tmp_path / "new.jpg"
    path.write_bytes(b"x" * 100)

    _result, candidates, _listener, _fs = _run(tmp_path, _matcher())

    assert len(candidates) == 1
    assert candidates[0].moved_from_id is None
    assert candidates[0].root == str(tmp_path)


# ── move detection ───────────────────────────────────────────────────────────────────────────────────────


def test_moved_file_is_linked_to_its_old_row(tmp_path: Path) -> None:
    new_path = tmp_path / "renamed.jpg"
    new_path.write_bytes(b"x" * 100)
    st = new_path.stat()
    old_path = str(tmp_path / "old_name.jpg")  # deliberately never created: it "moved away"
    old_key: FileKey = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
    known = FakeKnown(by_inode_map={(st.st_dev, st.st_ino): (42, old_path, old_key)})

    _result, candidates, _listener, _fs = _run(tmp_path, _matcher(), known=known)

    assert len(candidates) == 1
    assert candidates[0].moved_from_id == 42


def test_move_detection_requires_matching_mtime_and_size(tmp_path: Path) -> None:
    new_path = tmp_path / "renamed.jpg"
    new_path.write_bytes(b"x" * 100)
    st = new_path.stat()
    old_path = str(tmp_path / "old_name.jpg")
    mismatched_key: FileKey = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size + 1)  # size disagrees
    known = FakeKnown(by_inode_map={(st.st_dev, st.st_ino): (42, old_path, mismatched_key)})

    _result, candidates, _listener, _fs = _run(tmp_path, _matcher(), known=known)

    assert len(candidates) == 1
    assert candidates[0].moved_from_id is None


def test_move_detection_is_skipped_when_the_old_path_still_exists(tmp_path: Path) -> None:
    """Same inode found elsewhere, but that path is still there: a hardlink, not a move."""
    new_path = tmp_path / "dup.jpg"
    new_path.write_bytes(b"x" * 100)
    st = new_path.stat()
    old_path = str(tmp_path.parent / "elsewhere" / "original.jpg")
    old_key: FileKey = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
    known = FakeKnown(by_inode_map={(st.st_dev, st.st_ino): (7, old_path, old_key)})
    fs = CountingFs()
    fs.lexists_overrides[old_path] = True

    _result, candidates, _listener, _fs = _run(tmp_path, _matcher(), known=known, fs=fs)

    assert len(candidates) == 1
    assert candidates[0].moved_from_id is None


def test_move_detection_is_skipped_without_stable_inodes(tmp_path: Path) -> None:
    new_path = tmp_path / "renamed.jpg"
    new_path.write_bytes(b"x" * 100)
    st = new_path.stat()
    old_key: FileKey = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
    known = FakeKnown(by_inode_map={(st.st_dev, st.st_ino): (42, "/gone.jpg", old_key)})

    _result, candidates, _listener, _fs = _run(tmp_path, _matcher(), known=known, stable_inodes=False)

    assert len(candidates) == 1
    assert candidates[0].moved_from_id is None
    assert known.by_inode_calls == []


# ── hardlinks ────────────────────────────────────────────────────────────────────────────────────────────


def test_hardlink_produces_exactly_one_candidate(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    first.write_bytes(b"x" * 100)
    second = tmp_path / "b.jpg"
    os.link(first, second)

    _result, candidates, _listener, _fs = _run(tmp_path, _matcher())

    assert len(candidates) == 1
    assert candidates[0].path in (str(first), str(second))


# ── symlinks: loop, ancestor, broken, cross-device ──────────────────────────────────────────────────────


def test_symlink_loop_to_the_walk_root_is_reported_and_not_followed(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "back").symlink_to(tmp_path)

    result, candidates, listener, _fs = _run(tmp_path, _matcher())

    assert result.complete
    assert candidates == []
    assert IssueKind.SYMLINK_LOOP in listener.issue_kinds()


def test_symlink_to_the_immediate_parent_is_a_loop(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "self").symlink_to(sub)

    result, _candidates, listener, _fs = _run(tmp_path, _matcher())

    assert result.complete
    assert IssueKind.SYMLINK_LOOP in listener.issue_kinds()


def test_broken_symlink_is_reported_and_walk_continues(tmp_path: Path) -> None:
    (tmp_path / "dangling.jpg").symlink_to(tmp_path / "does-not-exist")
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)

    result, candidates, listener, _fs = _run(tmp_path, _matcher())

    assert result.complete
    assert [c.path for c in candidates] == [str(tmp_path / "keep.jpg")]
    assert IssueKind.BROKEN_SYMLINK in listener.issue_kinds()


def test_cross_device_directory_is_not_descended(tmp_path: Path) -> None:
    other = tmp_path / "other-device"
    other.mkdir()
    (other / "inner.jpg").write_bytes(b"x" * 100)
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)

    root_dev = tmp_path.stat().st_dev
    fs = CountingFs()
    fs.dev_overrides[str(other)] = root_dev + 1

    result, candidates, listener, _fs = _run(tmp_path, _matcher(), fs=fs)

    assert result.complete
    assert [c.path for c in candidates] == [str(tmp_path / "keep.jpg")]
    assert IssueKind.OTHER_FILESYSTEM in listener.issue_kinds()
    assert str(other) not in fs.scandir_calls


# ── permission and I/O failures ─────────────────────────────────────────────────────────────────────────


def test_permission_denied_directory_is_a_failed_dir_and_walk_continues(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "inside.jpg").write_bytes(b"x" * 100)
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)
    locked.chmod(0o000)
    try:
        result, candidates, listener, _fs = _run(tmp_path, _matcher())
    finally:
        locked.chmod(0o755)

    assert result.complete
    assert result.failed_dirs == (str(locked),)
    assert [c.path for c in candidates] == [str(tmp_path / "keep.jpg")]
    assert IssueKind.PERMISSION_DENIED in listener.issue_kinds()


def test_file_vanishing_between_scandir_and_stat_is_reported_not_raised(tmp_path: Path) -> None:
    ghost = tmp_path / "ghost.jpg"
    ghost.write_bytes(b"x" * 100)
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)

    fs = CountingFs()
    fs.stat_errors[str(ghost)] = FileNotFoundError(2, "No such file or directory")

    result, candidates, listener, _fs = _run(tmp_path, _matcher(), fs=fs)

    assert result.complete
    assert [c.path for c in candidates] == [str(tmp_path / "keep.jpg")]
    assert IssueKind.VANISHED in listener.issue_kinds()


# ── names ────────────────────────────────────────────────────────────────────────────────────────────────


def test_unicode_and_newline_names_are_ordinary_candidates(tmp_path: Path) -> None:
    weird = tmp_path / "café pic\nwith a newline.jpg"
    weird.write_bytes(b"x" * 100)

    _result, candidates, _listener, _fs = _run(tmp_path, _matcher())

    assert [c.path for c in candidates] == [str(weird)]


def test_non_utf8_name_is_reported_and_skipped(tmp_path: Path) -> None:
    bad_name = b"bad-\xff-name.jpg"
    bad_path = str(tmp_path).encode() + b"/" + bad_name
    os.close(os.open(bad_path, os.O_CREAT | os.O_WRONLY, 0o644))
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)

    result, candidates, listener, _fs = _run(tmp_path, _matcher())

    assert result.complete
    assert [c.path for c in candidates] == [str(tmp_path / "keep.jpg")]
    assert IssueKind.UNENCODABLE_NAME in listener.issue_kinds()


# ── special files ────────────────────────────────────────────────────────────────────────────────────────


def test_fifo_named_dot_jpg_does_not_hang_and_is_not_a_candidate(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe.jpg"
    os.mkfifo(fifo)
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)

    started = time.monotonic()
    result, candidates, listener, _fs = _run(tmp_path, _matcher())
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    assert result.complete
    assert [c.path for c in candidates] == [str(tmp_path / "keep.jpg")]
    assert IssueKind.NOT_REGULAR in listener.issue_kinds()


# ── size and extension filters (no issue kind: silently dropped) ───────────────────────────────────────


def test_extension_filter_avoids_a_stat_entirely(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(b"x" * 100)
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)
    fs = CountingFs()

    _result, candidates, _listener, _fs = _run(tmp_path, _matcher(), fs=fs)

    assert [c.path for c in candidates] == [str(tmp_path / "keep.jpg")]
    assert str(tmp_path / "notes.txt") not in fs.stat_calls


def test_min_file_bytes_default_is_64_kib() -> None:
    assert WalkOptions().min_file_bytes == 65_536


def test_files_outside_size_bounds_are_silently_dropped(tmp_path: Path) -> None:
    (tmp_path / "tiny.jpg").write_bytes(b"x" * 10)
    (tmp_path / "huge.jpg").write_bytes(b"x" * 1000)
    (tmp_path / "ok.jpg").write_bytes(b"x" * 100)
    options = WalkOptions(min_file_bytes=50, max_file_bytes=500)

    _result, candidates, listener, _fs = _run(tmp_path, _matcher(), options=options)

    assert [c.path for c in candidates] == [str(tmp_path / "ok.jpg")]
    assert listener.issues == []


# ── on_dir bookkeeping ───────────────────────────────────────────────────────────────────────────────────


def test_on_dir_reports_the_direct_candidate_count(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x" * 100)
    (tmp_path / "b.jpg").write_bytes(b"x" * 100)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.jpg").write_bytes(b"x" * 100)

    _result, _candidates, listener, _fs = _run(tmp_path, _matcher())

    by_path = dict(listener.dirs)
    assert by_path[str(tmp_path)] == 2
    assert by_path[str(sub)] == 1


# ── cancellation ─────────────────────────────────────────────────────────────────────────────────────────


def test_cancel_while_blocked_on_a_full_queue_unblocks_promptly(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x" * 100)
    (tmp_path / "b.jpg").write_bytes(b"x" * 100)
    (tmp_path / "c.jpg").write_bytes(b"x" * 100)

    out: queue.Queue[Candidate | None] = queue.Queue(maxsize=1)
    cancel = CancelToken()
    results: list[WalkResult] = []

    def run() -> None:
        results.append(
            walk(
                str(tmp_path),
                _matcher(),
                FakeKnown(),
                out,
                RecordingListener(),
                cancel,
                WalkOptions(min_file_bytes=0),
                CountingFs(),
            )
        )

    thread = threading.Thread(target=run)
    started = time.monotonic()
    thread.start()
    time.sleep(0.5)  # long enough for the queue (maxsize=1) to fill and the put loop to be retrying
    assert thread.is_alive(), "the walker should still be blocked on the full, undrained queue"
    cancel.cancel()
    thread.join(timeout=5.0)
    elapsed = time.monotonic() - started

    assert not thread.is_alive()
    assert elapsed < 5.0
    assert len(results) == 1
    assert results[0].complete is False


def test_cancel_before_starting_returns_immediately(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x" * 100)
    cancel = CancelToken()
    cancel.cancel()

    out: queue.Queue[Candidate | None] = queue.Queue()
    result = walk(str(tmp_path), _matcher(), FakeKnown(), out, RecordingListener(), cancel)

    assert result.complete is False
    assert out.get_nowait() is None


# ── the root itself ──────────────────────────────────────────────────────────────────────────────────────


def test_missing_root_is_a_failed_dir_but_the_walk_is_not_cancelled(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    result, candidates, listener, _fs = _run(missing, _matcher())

    assert result.complete
    assert result.failed_dirs == (str(missing),)
    assert candidates == []
    assert listener.issues


def test_root_that_is_a_file_is_a_failed_dir(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file.jpg"
    not_a_dir.write_bytes(b"x" * 100)

    result, candidates, _listener, _fs = _run(not_a_dir, _matcher())

    assert result.complete
    assert result.failed_dirs == (str(not_a_dir),)
    assert candidates == []


# ── inode exclusion (FILE rules by identity) ────────────────────────────────────────────────────────────


def test_match_inode_skips_without_a_stat(tmp_path: Path) -> None:
    target = tmp_path / "renamed-but-still-excluded.jpg"
    target.write_bytes(b"x" * 100)
    st = target.stat()
    matcher = _matcher([Rule(1, RuleKind.FILE, "/irrelevant/path.jpg", device=st.st_dev, inode=st.st_ino)])
    fs = CountingFs()

    _result, candidates, listener, fs = _run(tmp_path, matcher, fs=fs)

    assert candidates == []
    assert len(listener.skips) == 1
    assert str(target) not in fs.stat_calls
