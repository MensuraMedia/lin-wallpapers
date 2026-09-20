"""Hostile cases: paths as data, concurrent writers, and a process that dies mid-transaction."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from src.catalogue import db, ideal, queries
from src.catalogue.queries import QuerySpec, Segment
from src.scanner import exclude
from src.scanner.exclude import RuleKind
from tests.conftest import PROJECT_ROOT
from tests.unit.test_catalogue_support import FHD, add_image, db_path, open_db, set_displays

NASTY_PATHS = [
    "/photos/ünï/日本語/фото 🌄.jpg",
    "/photos/nfc-é/a.jpg",
    "/photos/nfd-é/a.jpg",  # never normalised: a different directory from the one above
    "/photos/new\nline/two\nlines.jpg",
    "/photos/tab\there/cr\rthere.jpg",
    "/photos/-rf/--version.jpg",
    "/photos/-",
    "/photos/ spaces  /  padded .jpg",
    "/photos/quote'double\"back`tick/$HOME;$(reboot).jpg",
    "/photos/glob*?[x]/{a,b}.jpg",
    "/photos/percent%41_under/back\\slash.jpg",
    "/photos/" + "/".join(["d" * 255] * 15) + "/" + "f" * 251 + ".jpg",  # 4 KiB+, every name at NAME_MAX
    "/photos/‮gpj.exe",  # right-to-left override
]


def test_nasty_paths_round_trip_as_plain_data(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    set_displays(conn, FHD)
    ids = {path: add_image(conn, path, 3840, 2160) for path in NASTY_PATHS}
    assert ideal.rebuild(conn, 16) == len(NASTY_PATHS)
    conn.close()
    conn = open_db(tmp_path)
    for path, image_id in ids.items():
        row = queries.get_image(conn, path)
        assert row is not None and (row.id, row.path) == (image_id, path)
        assert row.dir + "/" + row.name == path
        assert queries.get_image(conn, image_id) == row
    page = queries.fetch_page(conn, QuerySpec(segment=Segment.IDEAL, limit=1000))
    assert {row.path for row in page.rows} == set(NASTY_PATHS)
    assert [r.path for r in queries.fetch_page(conn, QuerySpec(dir_prefix="/photos/-rf")).rows] == [
        "/photos/-rf/--version.jpg"
    ]
    assert [r.path for r in queries.fetch_page(conn, QuerySpec(dir_prefix="/photos/new\nline")).rows] == [
        NASTY_PATHS[3]
    ]
    assert [r.path for r in queries.fetch_page(conn, QuerySpec(search="two\nlines")).rows] == [NASTY_PATHS[3]]
    assert [r.path for r in queries.fetch_page(conn, QuerySpec(search="--version")).rows] == [
        "/photos/-rf/--version.jpg"
    ]
    assert len(queries.fetch_page(conn, QuerySpec(dir_prefix="/photos/nfc-é")).rows) == 1
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_nasty_rule_values_are_stored_and_matched_literally(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    for path in NASTY_PATHS:
        add_image(conn, path)
    folders = ["/photos/new\nline", "/photos/-rf", "/photos/nfc-é", "/photos/quote'double\"back`tick"]
    rule_ids = [
        db.add_rule(conn, RuleKind.FOLDER, folder, group="g'; DROP TABLE exclusion;--", root=None)
        for folder in folders
    ]
    rules, groups = db.load_rules(conn)
    assert [r.value for r in rules if r.id in rule_ids] == folders
    delta = db.apply_exclusions(conn, exclude.compile_matcher(rules, groups, home="/home/u"))
    assert delta.flagged == 4
    flagged = {row[0] for row in conn.execute("SELECT path FROM image WHERE excluded_by IS NOT NULL")}
    assert flagged == {NASTY_PATHS[3], NASTY_PATHS[5], NASTY_PATHS[1], NASTY_PATHS[8]}
    assert NASTY_PATHS[2] not in flagged  # NFD twin of an excluded NFC folder stays (ruling Q9)
    stored = conn.execute(
        "SELECT count(*) FROM exclusion_group WHERE name = ?", ("g'; DROP TABLE exclusion;--",)
    )
    assert stored.fetchone()[0] == 1


def test_surrogate_escaped_name_is_refused_not_stored_mangled(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    bad = b"/photos/caf\xe9.jpg".decode("utf-8", "surrogateescape")  # D15: the walker reports these
    with pytest.raises(UnicodeEncodeError):
        add_image(conn, bad)
    assert (
        queries.get_image(conn, bad) is None
    )  # `linwp show <such a path>` answers "not found", no traceback
    assert queries.fetch_page(conn, QuerySpec(search=bad, dir_prefix=bad, formats=(bad,))).total == 0
    assert conn.execute("SELECT count(*) FROM image").fetchone()[0] == 0


# ── concurrency ──────────────────────────────────────────────────────────────────────────────────────────


def test_two_connections_writing_at_once_serialise_without_loss(tmp_path: Path) -> None:
    open_db(tmp_path).close()
    path = db_path(tmp_path)
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def writer(worker: int) -> None:
        try:
            conn = db.connect(path)
            barrier.wait(timeout=10)
            for batch in range(10):
                with db.transaction(conn):
                    for n in range(20):
                        add_image(conn, f"/w{worker}/b{batch}/{n}.jpg")
                    db.set_setting(conn, f"worker.{worker}", batch)
            conn.close()
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    conn = open_db(tmp_path)
    assert conn.execute("SELECT count(*) FROM image").fetchone()[0] == 4 * 10 * 20
    assert [db.get_setting(conn, f"worker.{n}", -1) for n in range(4)] == [9, 9, 9, 9]
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_a_reader_sees_a_consistent_snapshot_while_a_writer_is_mid_batch(tmp_path: Path) -> None:
    writer = open_db(tmp_path)
    add_image(writer, "/p/committed.jpg")
    reader = db.connect(db_path(tmp_path), readonly=True)
    writer.execute("BEGIN IMMEDIATE")
    add_image(writer, "/p/in-flight.jpg")
    assert [r.name for r in queries.fetch_page(reader, QuerySpec()).rows] == ["committed.jpg"]
    before = reader.execute("PRAGMA data_version").fetchone()[0]
    writer.execute("COMMIT")
    assert (
        reader.execute("PRAGMA data_version").fetchone()[0] != before
    )  # how the GUI notices a CLI scan (§3)
    assert len(queries.fetch_page(reader, QuerySpec()).rows) == 2


# ── kill safety ──────────────────────────────────────────────────────────────────────────────────────────


def test_connection_closed_without_commit_loses_only_the_open_transaction(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    add_image(conn, "/p/committed.jpg")
    conn.execute("BEGIN IMMEDIATE")
    for n in range(500):
        add_image(conn, f"/p/lost-{n}.jpg")
    conn.execute("INSERT INTO scan(started, pid) VALUES (1, 1)")
    conn.close()  # no COMMIT
    reopened = open_db(tmp_path)
    assert [r.name for r in queries.fetch_page(reopened, QuerySpec()).rows] == ["committed.jpg"]
    assert reopened.execute("SELECT count(*) FROM scan").fetchone()[0] == 0
    assert reopened.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    add_image(reopened, "/p/after.jpg")  # and it is writable


KILLED_CHILD = textwrap.dedent(
    """
    import os, sys
    from pathlib import Path
    from src.catalogue import db

    conn = db.open_catalogue(Path(sys.argv[1]))
    lock = db.scan_lock(Path(sys.argv[1]))
    lock.__enter__()
    with db.transaction(conn):
        conn.execute("INSERT INTO scan(started, pid) VALUES (1, ?)", (os.getpid(),))
        for n in range(200):
            conn.execute("INSERT INTO image(path, dir, name, width, height) VALUES (?, '/p', ?, 1920, 1080)",
                         (f"/p/batch1-{n}.jpg", f"batch1-{n}.jpg"))
    conn.execute("BEGIN IMMEDIATE")
    for n in range(5000):
        conn.execute("INSERT INTO image(path, dir, name, width, height) VALUES (?, '/p', ?, 1920, 1080)",
                     (f"/p/batch2-{n}.jpg", f"batch2-{n}.jpg"))
    conn.execute("UPDATE scan SET probed = 5200")
    sys.stdout.write("mid-write\\n")
    sys.stdout.flush()
    os._exit(9)   # no COMMIT, no close, no atexit: as good as kill -9
    """
)


def test_process_killed_mid_transaction_leaves_a_usable_catalogue(tmp_path: Path) -> None:
    path = db_path(tmp_path)
    done = subprocess.run(
        [sys.executable, "-c", KILLED_CHILD, str(path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 9, done.stderr
    assert done.stdout == "mid-write\n"
    assert path.with_name("catalogue.db-wal").exists()  # the hot WAL is still there

    conn = db.open_catalogue(path)  # recovers the WAL, then marks the scan interrupted
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert (
        conn.execute("SELECT count(*) FROM image").fetchone()[0] == 200
    )  # batch 1 whole, batch 2 lost whole
    assert conn.execute("SELECT count(*) FROM image WHERE name LIKE 'batch2-%'").fetchone()[0] == 0
    scan = conn.execute("SELECT result, finished, probed FROM scan").fetchone()
    assert (scan["result"], scan["finished"], scan["probed"]) == ("interrupted", None, 0)
    with db.scan_lock(path):  # the flock died with the process
        pass
    set_displays(conn, FHD)
    assert ideal.rebuild(conn, 16) == 200
    add_image(conn, "/p/after-the-crash.jpg")
    assert queries.fetch_page(conn, QuerySpec(segment=Segment.IDEAL)).total == 201 - 1
