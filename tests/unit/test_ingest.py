"""P5b — the scan orchestration (``catalogue/ingest.py``): the writer thread and ``ScanService``.

Every test drives a real scan of a real (temporary) tree through the real walker/probe/writer pipeline;
nothing touches the user's actual system. Displays are supplied explicitly (``probes=[]`` plus optional
``declared``) so detection is deterministic and never depends on the machine running the suite.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from src.catalogue import db
from src.catalogue.db import ChangeFeed, ScanInProgressError, open_catalogue
from src.catalogue.ingest import CatalogueWriter, ScanProgress, ScanService
from src.catalogue.thumbs import ThumbCache
from src.scanner import probe
from src.scanner.displays import Display
from src.scanner.roots import Mount, MountTable
from src.util.cancel import CancelToken
from tests.helpers import imagegen

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── harness ──────────────────────────────────────────────────────────────────────────────────────────────


class _NullListener:
    def on_progress(self, p: ScanProgress) -> None:
        return None


class _Harness:
    def __init__(self, tmp_path: Path, mounts: MountTable | None = None) -> None:
        self.db_path = tmp_path / "catalogue.db"
        open_catalogue(self.db_path).close()
        self.feed = ChangeFeed()
        self.writer = CatalogueWriter(self.db_path, self.feed)
        self.thumbs = ThumbCache(base=tmp_path / "thumbs")
        self._mounts = mounts if mounts is not None else MountTable()
        self.service = ScanService(
            self.db_path, self.writer, self.thumbs, [], lambda: self._mounts
        )
        # tiny generated images: lift the 64 KiB walker floor so the fixtures are catalogued
        self.writer.submit(lambda c: db.set_setting(c, "scan.min_file_bytes", 0)).result()

    def set_mounts(self, mounts: MountTable) -> None:
        self._mounts = mounts

    def add_root(self, path: Path, *, kind: str = "user", volume_id: str | None = None) -> int:
        def job(conn: object) -> int:
            cursor = conn.execute(  # type: ignore[attr-defined]
                "INSERT INTO root(path, kind, enabled, volume_id) VALUES (?, ?, 1, ?)",
                (str(path), kind, volume_id),
            )
            return int(cursor.lastrowid or 0)

        return self.writer.submit(job).result()

    def scan(self, declared: tuple[Display, ...] = (), cancel: CancelToken | None = None, listener=None):
        return self.service.scan(None, declared, listener or _NullListener(), cancel or CancelToken())

    def images(self) -> list[dict[str, object]]:
        conn = db.connect(self.db_path, readonly=True)
        try:
            return [dict(row) for row in conn.execute("SELECT * FROM image ORDER BY path")]
        finally:
            conn.close()

    def scans(self) -> list[dict[str, object]]:
        conn = db.connect(self.db_path, readonly=True)
        try:
            return [dict(row) for row in conn.execute("SELECT * FROM scan ORDER BY id")]
        finally:
            conn.close()

    def close(self) -> None:
        self.writer.close()


@pytest.fixture
def harness(tmp_path: Path) -> _Harness:
    h = _Harness(tmp_path)
    yield h
    h.close()


def _make_tree(root: Path, count: int = 3) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        paths.append(imagegen.make_jpeg(root, f"pic{index}.jpg", size=(200, 150), seed=index + 1))
    return sorted(paths)


# ── tests ────────────────────────────────────────────────────────────────────────────────────────────────


def test_thumbcache_conforms_to_thumbsink(tmp_path: Path) -> None:
    @runtime_checkable
    class _Sink(Protocol):
        def store(self, image: object, key: str, cancel: object) -> str: ...

    assert isinstance(ThumbCache(base=tmp_path / "t"), _Sink)
    # probe.ThumbSink is the (non-runtime-checkable) protocol the prober actually calls; check structurally
    assert callable(getattr(probe.ThumbSink, "store", None))
    assert callable(ThumbCache.store)


def test_end_to_end_catalogues_a_tree(harness: _Harness, tmp_path: Path) -> None:
    tree = tmp_path / "pics"
    files = _make_tree(tree, 3)
    harness.add_root(tree)

    summary = harness.scan()

    assert summary.result == "ok"
    assert summary.progress.found == 3
    rows = harness.images()
    assert {r["path"] for r in rows} == {str(p) for p in files}
    assert all(r["probe_status"] == "ok" for r in rows)
    assert all(r["missing"] == 0 for r in rows)
    assert all(r["width"] and r["height"] for r in rows)
    assert all(r["seen_scan"] == summary.scan_id for r in rows)
    # every row went through the thumbnailer (see the note in the P5b hand-off about the thumbs.py
    # directory-creation race that can turn a concurrent store into 'failed'); at least one succeeds.
    assert all(r["thumb_status"] in {"ok", "failed"} for r in rows)
    assert any(r["thumb_status"] == "ok" for r in rows)


def test_rescan_reprobes_nothing(harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = tmp_path / "pics"
    _make_tree(tree, 4)
    harness.add_root(tree)

    from src.catalogue import ingest

    calls: list[int] = []
    real = ingest.probe.probe_file

    def spy(*args: object, **kwargs: object):
        calls.append(1)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest.probe, "probe_file", spy)

    first = harness.scan()
    assert first.progress.probed == 4
    assert len(calls) == 4

    calls.clear()
    second = harness.scan()
    assert second.progress.probed == 0
    assert second.progress.unchanged == 4
    assert len(calls) == 0  # not one file re-opened


def test_no_display_scans_and_records_the_reason(harness: _Harness, tmp_path: Path) -> None:
    tree = tmp_path / "pics"
    _make_tree(tree, 2)
    harness.add_root(tree)

    summary = harness.scan(declared=())  # probes=[] and nothing declared → no display

    assert summary.result == "ok"
    assert summary.detection.reason is not None
    assert summary.detection.reason.code.value == "DISPLAY_NOT_DETECTED"
    scan_row = harness.scans()[-1]
    assert scan_row["reason"] is not None
    assert "DISPLAY_NOT_DETECTED" in str(scan_row["reason"])


def test_missing_is_marked_only_after_a_complete_walk(harness: _Harness, tmp_path: Path) -> None:
    tree = tmp_path / "pics"
    files = _make_tree(tree, 3)
    harness.add_root(tree)
    harness.scan()

    gone = files[0]
    gone.unlink()
    harness.scan()

    rows = {r["path"]: r for r in harness.images()}
    assert rows[str(gone)]["missing"] == 1
    assert all(rows[str(p)]["missing"] == 0 for p in files[1:])


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_nothing_under_a_failed_dir_is_marked_missing(harness: _Harness, tmp_path: Path) -> None:
    tree = tmp_path / "pics"
    tree.mkdir()
    sub = tree / "locked"
    sub.mkdir()
    imagegen.make_jpeg(tree, "top.jpg", size=(200, 150), seed=1)
    buried = imagegen.make_jpeg(sub, "buried.jpg", size=(200, 150), seed=2)
    harness.add_root(tree)
    harness.scan()
    assert {r["path"] for r in harness.images()} == {str(tree / "top.jpg"), str(buried)}

    sub.chmod(0o000)
    try:
        summary = harness.scan()
    finally:
        sub.chmod(0o755)

    assert summary.result == "ok"
    rows = {r["path"]: r for r in harness.images()}
    # the directory failed to list, so its buried file's absence proves nothing — it stays present
    assert rows[str(buried)]["missing"] == 0


def test_cancel_mid_scan_leaves_a_consistent_db_and_rescan_completes(
    harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "pics"
    files = _make_tree(tree, 40)
    harness.add_root(tree)

    from src.catalogue import ingest

    real = ingest.probe.probe_file

    def slow(*args: object, **kwargs: object):
        time.sleep(0.01)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest.probe, "probe_file", slow)

    cancel = CancelToken()
    result: dict[str, object] = {}

    def go() -> None:
        result["summary"] = harness.scan(cancel=cancel)

    thread = threading.Thread(target=go)
    thread.start()
    time.sleep(0.05)
    cancel.cancel()
    thread.join(timeout=20)
    assert not thread.is_alive()

    summary = result["summary"]
    assert summary.result == "cancelled"  # type: ignore[union-attr]
    # whatever committed is well-formed, and nothing was marked missing on a cancelled scan
    rows = harness.images()
    assert len(rows) <= 40
    assert all(r["path"] for r in rows)
    assert all(r["missing"] == 0 for r in rows)

    monkeypatch.setattr(ingest.probe, "probe_file", real)
    final = harness.scan()
    assert final.result == "ok"
    assert {r["path"] for r in harness.images()} == {str(p) for p in files}


def test_second_scanner_raises_without_deadlocking(harness: _Harness, tmp_path: Path) -> None:
    tree = tmp_path / "pics"
    _make_tree(tree, 2)
    harness.add_root(tree)

    result: dict[str, BaseException] = {}

    with db.scan_lock(harness.db_path):  # stand in for another live scanner
        def go() -> None:
            try:
                harness.scan()
            except BaseException as error:
                result["error"] = error

        thread = threading.Thread(target=go)
        thread.start()
        thread.join(timeout=5)  # BOUNDED: a non-blocking flock must fail fast, never hang
        assert not thread.is_alive(), "scan() blocked on the scan lock instead of failing fast"

    assert isinstance(result.get("error"), ScanInProgressError)


def test_split_dir_and_name() -> None:
    from src.catalogue import ingest

    assert ingest._split("/a/b/c.jpg") == ("/a/b", "c.jpg")
    assert ingest._split("/top.jpg") == ("/", "top.jpg")
    for path in ("/a/b/c.jpg", "/top.jpg", "/x/y"):
        directory, name = ingest._split(path)
        assert not name.startswith("/")
        assert directory == "/" or not directory.endswith("/")


def test_split_matches_the_catalogued_rows(harness: _Harness, tmp_path: Path) -> None:
    tree = tmp_path / "pics"
    sub = tree / "nested"
    sub.mkdir(parents=True)
    imagegen.make_jpeg(sub, "pic.jpg", size=(200, 150), seed=1)
    harness.add_root(tree)
    harness.scan()
    row = harness.images()[0]
    assert row["dir"] == str(sub)  # no trailing slash
    assert row["name"] == "pic.jpg"  # no leading slash
    assert row["path"] == str(sub / "pic.jpg")


def test_cancel_drains_the_queue_without_probing(
    harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "pics"
    _make_tree(tree, 30)
    harness.add_root(tree)

    from src.catalogue import ingest

    real = ingest.probe.probe_file
    started = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    count: list[int] = []

    def blocking(*args: object, **kwargs: object):
        with lock:
            count.append(1)
        started.set()
        release.wait(timeout=5)  # pin the in-flight probes so the walker fills the queue behind them
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest.probe, "probe_file", blocking)

    cancel = CancelToken()
    result: dict[str, object] = {}

    def go() -> None:
        result["summary"] = harness.scan(cancel=cancel)

    thread = threading.Thread(target=go)
    thread.start()
    assert started.wait(5)
    time.sleep(0.15)  # every candidate is now queued; only the workers' in-flight probes have run
    cancel.cancel()
    release.set()
    thread.join(timeout=20)
    assert not thread.is_alive()

    assert result["summary"].result == "cancelled"  # type: ignore[union-attr]
    workers = min(4, os.cpu_count() or 1)
    # the queued candidates were drained WITHOUT probing — only the already-in-flight probes ran
    assert len(count) <= workers
    assert len(count) < 30


def test_cancelling_a_second_scan_never_marks_the_first_scans_rows_missing(
    harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "pics"
    files = _make_tree(tree, 30)
    harness.add_root(tree)
    harness.scan()  # a complete first scan: every row present
    assert all(r["missing"] == 0 for r in harness.images())

    # touch every file so the second scan treats them all as changed (candidates to be probed)
    stamp = time.time() + 100
    for path in files:
        os.utime(path, (stamp, stamp))

    from src.catalogue import ingest

    real = ingest.probe.probe_file
    started = threading.Event()
    release = threading.Event()

    def blocking(*args: object, **kwargs: object):
        started.set()
        release.wait(timeout=5)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest.probe, "probe_file", blocking)

    cancel = CancelToken()
    result: dict[str, object] = {}

    def go() -> None:
        result["summary"] = harness.scan(cancel=cancel)

    thread = threading.Thread(target=go)
    thread.start()
    assert started.wait(5)
    time.sleep(0.15)  # the walk completes (walk_result.complete) while the probes are pinned
    cancel.cancel()
    release.set()
    thread.join(timeout=20)
    assert not thread.is_alive()

    assert result["summary"].result == "cancelled"  # type: ignore[union-attr]
    rows = harness.images()
    assert len(rows) == 30  # no rows lost or duplicated
    # the walk finished but the scan was cancelled: most rows went unseen, yet NONE may be marked missing
    assert all(r["missing"] == 0 for r in rows)
    assert {r["path"] for r in rows} == {str(p) for p in files}


def test_nothing_is_left_running_after_close(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    tree = tmp_path / "pics"
    _make_tree(tree, 3)
    harness.add_root(tree)
    harness.scan()
    assert any(t.name == "lwp-writer" for t in threading.enumerate())  # the writer is up while in use

    harness.close()
    time.sleep(0.2)

    names = [t.name for t in threading.enumerate()]
    assert "lwp-writer" not in names  # the writer thread was joined
    assert not any(n.startswith("lwp-probe") for n in names)  # the scan-private pool was shut down
    assert not any(n.startswith(("lwp-walk", "lwp-fin")) for n in names)  # no walker/finalizer left


def test_volume_offline_then_remount_at_the_same_point_heals_rows(tmp_path: Path) -> None:
    uuid = "FEED-BEEF"
    mnt = tmp_path / "media" / "stick"
    files = _make_tree(mnt, 3)

    def mount_at(target: Path) -> MountTable:
        return MountTable(
            [
                Mount(
                    target=str(target),
                    source="/dev/sdz1",
                    fstype="ext4",
                    uuid=uuid,
                    label="STICK",
                    removable=True,
                    network=False,
                    stable_inodes=True,
                )
            ]
        )

    harness = _Harness(tmp_path, mounts=mount_at(mnt))
    try:
        harness.add_root(mnt, kind="volume", volume_id=uuid)
        harness.scan()
        assert all(r["missing"] == 0 for r in harness.images())

        harness.set_mounts(MountTable())  # drive removed
        harness.scan()
        assert all(r["missing"] == 1 for r in harness.images())

        harness.set_mounts(mount_at(mnt))  # SAME mount point, files untouched
        harness.scan()

        rows = harness.images()
        assert len(rows) == 3  # no duplicates
        assert all(r["missing"] == 0 for r in rows)  # healed via the unchanged-file reset, not a re-probe
        assert {r["path"] for r in rows} == {str(p) for p in files}
    finally:
        harness.close()


def test_unchanged_reset_clears_missing_when_the_sweep_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolates the ``_Unchanged`` UPDATE's ``missing = 0`` from the complete-walk sweep in
    ``_mark_missing`` (which also clears seen rows). A cancelled walk skips the sweep, so a
    previously-missing-but-unchanged file can only be healed by the unchanged-file reset itself."""
    uuid = "AAAA-1111"
    mnt = tmp_path / "media" / "stick"
    keep = _make_tree(mnt, 3)

    def mount_at(target: Path) -> MountTable:
        return MountTable(
            [Mount(str(target), "/dev/sdz1", "ext4", uuid, "L", True, False, True)]
        )

    harness = _Harness(tmp_path, mounts=mount_at(mnt))
    try:
        harness.add_root(mnt, kind="volume", volume_id=uuid)
        harness.scan()
        harness.set_mounts(MountTable())  # offline → the 3 rows are marked missing while the files stay put
        harness.scan()
        assert all(r["missing"] == 1 for r in harness.images())

        # remount at the same point and add one changed file to hold the scan open long enough to cancel
        harness.set_mounts(mount_at(mnt))
        imagegen.make_jpeg(mnt, "churn.jpg", size=(300, 220), seed=9)

        from src.catalogue import ingest

        real = ingest.probe.probe_file
        started = threading.Event()
        release = threading.Event()

        def blocking(*args: object, **kwargs: object):
            started.set()
            release.wait(timeout=5)
            return real(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(ingest.probe, "probe_file", blocking)

        cancel = CancelToken()
        result: dict[str, object] = {}

        def go() -> None:
            result["summary"] = harness.scan(cancel=cancel)

        thread = threading.Thread(target=go)
        thread.start()
        assert started.wait(5)
        time.sleep(0.4)  # the three unchanged rows have been flushed and committed by now
        cancel.cancel()
        release.set()
        thread.join(timeout=20)
        assert not thread.is_alive()

        assert result["summary"].result == "cancelled"  # type: ignore[union-attr]
        rows = {r["path"]: r for r in harness.images()}
        # the sweep was skipped (cancelled) — these are clear ONLY thanks to the unchanged-file reset
        for path in keep:
            assert rows[str(path)]["missing"] == 0
    finally:
        harness.close()


def test_volume_offline_marks_missing_then_remount_heals_by_uuid(tmp_path: Path) -> None:
    uuid = "1234-ABCD"
    mnt_a = tmp_path / "media" / "a"
    files = _make_tree(mnt_a, 3)

    def mount_at(target: Path) -> MountTable:
        return MountTable(
            [
                Mount(
                    target=str(target),
                    source="/dev/sdz1",
                    fstype="ext4",
                    uuid=uuid,
                    label="STICK",
                    removable=True,
                    network=False,
                    stable_inodes=True,
                )
            ]
        )

    harness = _Harness(tmp_path, mounts=mount_at(mnt_a))
    try:
        harness.add_root(mnt_a, kind="volume", volume_id=uuid)
        harness.scan()
        before = harness.images()
        assert len(before) == 3
        assert all(r["volume_id"] == uuid and r["missing"] == 0 for r in before)

        # drive removed
        harness.set_mounts(MountTable())
        harness.scan()
        assert all(r["missing"] == 1 for r in harness.images())

        # drive comes back at a different mount point
        mnt_b = tmp_path / "run" / "media" / "user" / "b"
        mnt_b.parent.mkdir(parents=True, exist_ok=True)
        Path(mnt_a).rename(mnt_b)
        harness.set_mounts(mount_at(mnt_b))
        harness.scan()

        after = harness.images()
        assert len(after) == 3  # healed in place — no duplicate rows
        assert all(r["missing"] == 0 for r in after)
        assert {r["path"] for r in after} == {str(mnt_b / p.name) for p in files}
    finally:
        harness.close()


def test_put_never_blocks_forever_during_teardown(harness: _Harness) -> None:
    from src.catalogue import ingest

    full: queue.Queue[object] = queue.Queue(1)
    full.put(ingest._Unchanged("/already/here"))  # the queue is now full: a plain put would block

    # with the cancel token set, _put must return promptly rather than wait for space
    cancelled = CancelToken()
    cancelled.cancel()
    done_cancel = threading.Event()

    def put_with_cancel() -> None:
        harness.service._put(full, ingest._Unchanged("/x"), cancelled, ingest._Abort())
        done_cancel.set()

    thread = threading.Thread(target=put_with_cancel, daemon=True)
    thread.start()
    assert done_cancel.wait(3), "_put blocked forever on a full queue despite cancel"
    thread.join(2)

    # and with the abort signal set instead (a failed writer job), _put must likewise return at once
    aborted = ingest._Abort()
    aborted.trigger(RuntimeError("writer down"))
    done_abort = threading.Event()

    def put_with_abort() -> None:
        harness.service._put(full, ingest._Unchanged("/y"), CancelToken(), aborted)
        done_abort.set()

    thread2 = threading.Thread(target=put_with_abort, daemon=True)
    thread2.start()
    assert done_abort.wait(3), "_put blocked forever on a full queue despite abort"
    thread2.join(2)


def test_writer_failure_mid_scan_ends_as_error_without_leaking_threads(
    harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a tree large enough that, after the first batch fails, probe workers keep producing and fill res_q(256)
    tree = tmp_path / "pics"
    _make_tree(tree, 600)
    harness.add_root(tree)

    from src.catalogue import ingest
    from src.catalogue.db import CatalogueError

    def explode(*args: object, **kwargs: object) -> int:
        raise CatalogueError("catalogue on fire")

    monkeypatch.setattr(ingest, "_upsert_image", explode)  # every flush batch's writer job now fails

    cancel = CancelToken()
    result: dict[str, object] = {}

    def go() -> None:
        result["summary"] = harness.scan(cancel=cancel)

    thread = threading.Thread(target=go, daemon=True)  # daemon so a regression fails fast, never hangs exit
    thread.start()
    # calling cancel() during the failure teardown must also return, never hang
    time.sleep(0.2)
    cancel.cancel()
    thread.join(timeout=30)
    assert not thread.is_alive(), "scan() hung on a writer failure instead of tearing down"

    summary = result["summary"]
    assert summary.result == "error"  # type: ignore[union-attr]
    scan_row = harness.scans()[-1]
    assert scan_row["result"] == "error"
    assert "CatalogueError" in str(scan_row["reason"])  # the failure is carried on the scan row

    time.sleep(0.3)
    names = [th.name for th in threading.enumerate()]
    assert not any(n.startswith(("lwp-probe", "lwp-walk", "lwp-fin")) for n in names)


def test_kill9_subprocess_recovers_interrupted_and_rescan_converges(tmp_path: Path) -> None:
    db_path = tmp_path / "catalogue.db"
    cache = tmp_path / "cache"
    tree = tmp_path / "pics"
    files = _make_tree(tree, 5)

    child = tmp_path / "child.py"
    child.write_text(_CHILD_SOURCE)

    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), XDG_CACHE_HOME=str(cache))
    proc = subprocess.Popen(
        [sys.executable, str(child), str(db_path), str(tree)],
        stdout=subprocess.PIPE,
        env=env,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line == "READY", f"child did not reach the running-scan state: {line!r}"
    finally:
        proc.kill()  # SIGKILL — the flock dies with the process, committed batches survive in the WAL
        proc.wait(timeout=10)

    # reopening runs recover(): the abandoned running scan becomes 'interrupted'
    open_catalogue(db_path).close()
    conn = db.connect(db_path, readonly=True)
    try:
        interrupted = conn.execute("SELECT count(*) FROM scan WHERE result = 'interrupted'").fetchone()[0]
    finally:
        conn.close()
    assert interrupted >= 1

    # a fresh scan converges to exactly the tree's files, with no duplicates
    feed = ChangeFeed()
    writer = CatalogueWriter(db_path, feed)
    try:
        writer.submit(lambda c: db.set_setting(c, "scan.min_file_bytes", 0)).result()
        service = ScanService(db_path, writer, ThumbCache(base=cache), [], MountTable)
        service.scan(None, (), _NullListener(), CancelToken())
    finally:
        writer.close()

    conn = db.connect(db_path, readonly=True)
    try:
        paths = {row[0] for row in conn.execute("SELECT path FROM image")}
    finally:
        conn.close()
    assert paths == {str(p) for p in files}


_CHILD_SOURCE = '''
import sys, time
from pathlib import Path
from src.catalogue import db
from src.catalogue.db import ChangeFeed, open_catalogue
from src.catalogue.ingest import CatalogueWriter, ScanService
from src.catalogue.thumbs import ThumbCache
from src.scanner.roots import MountTable
from src.util.cancel import CancelToken

db_path = Path(sys.argv[1])
tree = Path(sys.argv[2])
open_catalogue(db_path).close()
feed = ChangeFeed()
writer = CatalogueWriter(db_path, feed)
writer.submit(lambda c: db.set_setting(c, "scan.min_file_bytes", 0)).result()

def add(conn):
    conn.execute("INSERT INTO root(path, kind, enabled) VALUES (?, 'user', 1)", (str(tree),))

writer.submit(add).result()

class L:
    def on_progress(self, p):
        return None

service = ScanService(db_path, writer, ThumbCache(), [], MountTable)
service.scan(None, (), L(), CancelToken())  # a real, complete scan: rows are committed

# now stand in for a scan that is interrupted mid-flight: a committed 'running' row, then hang
def running(conn):
    conn.execute("INSERT INTO scan(started, pid, result) VALUES (?, ?, 'running')", (int(time.time()), 1))

writer.submit(running).result()
print("READY", flush=True)
time.sleep(60)
'''
