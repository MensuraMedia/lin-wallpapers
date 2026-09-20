"""Migrations and the typed open errors: nothing here ever modifies a file it cannot use."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from src.catalogue import db
from src.catalogue.migrations import MIGRATIONS, Migration, m0001_initial
from src.catalogue.migrations.script import run_script, split_statements
from tests.unit.test_catalogue_support import add_image, db_path, open_db

TABLES = {
    "setting", "volume", "root", "exclusion_group", "exclusion", "image", "display", "scan", "scan_skip",
    "scan_issue", "ideal_image", "ideal_pin",
}  # fmt: skip


def schema_of(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name")]


def raw_db(path: Path, user_version: int) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE keepsake(x)")
    raw.execute("INSERT INTO keepsake VALUES ('mine')")
    raw.execute(f"PRAGMA user_version = {int(user_version)}")
    raw.commit()
    raw.close()
    return path.read_bytes()


def test_fresh_database_reaches_the_latest_schema(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.LATEST_SCHEMA == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables >= TABLES
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    path = db_path(tmp_path)
    assert (path.stat().st_mode & 0o777, path.parent.stat().st_mode & 0o777) == (0o600, 0o700)


def test_migration_table_is_contiguous_and_matches_latest() -> None:
    assert [m.version for m in MIGRATIONS] == list(range(1, len(MIGRATIONS) + 1))
    assert MIGRATIONS[-1].version == db.LATEST_SCHEMA
    assert "CREATE TABLE image" in m0001_initial.schema_sql()  # packaged as a resource


def test_reopen_is_idempotent_and_makes_no_backup(tmp_path: Path) -> None:
    first = open_db(tmp_path)
    add_image(first, "/p/a.jpg")
    before = schema_of(first)
    first.close()
    second = open_db(tmp_path)
    assert schema_of(second) == before
    assert db.migrate(second) == 1
    assert second.execute("SELECT count(*) FROM image").fetchone()[0] == 1
    assert [p.name for p in db_path(tmp_path).parent.iterdir() if ".bak" in p.name] == []


def test_newer_schema_is_refused_and_the_file_is_untouched(tmp_path: Path) -> None:
    path = db_path(tmp_path)
    before = raw_db(path, 99)
    for opener in (db.open_catalogue, db.connect, lambda p: db.connect(p, readonly=True)):
        with pytest.raises(db.SchemaTooNewError) as caught:
            opener(path)
        assert (caught.value.found, caught.value.supported) == (99, 1)
        assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir() if ".bak" in p.name) == []
    raw = sqlite3.connect(path)
    assert raw.execute("SELECT x FROM keepsake").fetchone()[0] == "mine"
    assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "delete"  # not even switched to WAL


def test_run_migrations_refuses_a_newer_user_version_directly() -> None:
    """P4-3 public-API guard: calling ``run_migrations`` itself (not just via ``connect``/``open_catalogue``)
    on a connection whose ``user_version`` is already newer than ``LATEST_SCHEMA`` must raise, not migrate."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA user_version = 99")
    with pytest.raises(db.SchemaTooNewError) as caught:
        db.run_migrations(conn, MIGRATIONS)
    assert (caught.value.found, caught.value.supported) == (99, db.LATEST_SCHEMA)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 99
    assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0  # nothing was applied


def _boom(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE half_done(x)")
    conn.execute("INSERT INTO setting(key, value) VALUES ('half', '1')")
    raise RuntimeError("migration 2 failed half-way")


def test_failing_migration_rolls_back_completely_and_a_backup_exists(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    add_image(conn, "/p/a.jpg")
    before = schema_of(conn)
    with pytest.raises(RuntimeError):
        db.run_migrations(conn, (*MIGRATIONS, Migration(2, "boom", _boom)))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert schema_of(conn) == before
    assert conn.execute("SELECT count(*) FROM setting WHERE key = 'half'").fetchone()[0] == 0
    assert not conn.in_transaction
    backup = db_path(tmp_path).with_name("catalogue.db.bak-v1")
    copy = sqlite3.connect(backup)
    assert copy.execute("PRAGMA user_version").fetchone()[0] == 1
    assert copy.execute("SELECT path FROM image").fetchone()[0] == "/p/a.jpg"
    assert backup.stat().st_mode & 0o777 == 0o600


def test_second_migration_applies_once_backs_up_and_is_idempotent(tmp_path: Path) -> None:
    def add_column(conn: sqlite3.Connection) -> None:
        run_script(conn, "ALTER TABLE image ADD COLUMN note TEXT; CREATE INDEX image_note ON image(note);")

    steps = (*MIGRATIONS, Migration(2, "note", add_column))
    conn = open_db(tmp_path)
    assert db.run_migrations(conn, steps) == 2
    assert db.run_migrations(conn, steps) == 2
    assert "note" in {r[1] for r in conn.execute("PRAGMA table_info(image)")}
    assert db_path(tmp_path).with_name("catalogue.db.bak-v1").is_file()
    conn.close()
    with pytest.raises(db.SchemaTooNewError):  # this release only knows version 1
        open_db(tmp_path)


def test_garbage_bytes_are_reported_as_corrupt_and_kept(tmp_path: Path) -> None:
    path = db_path(tmp_path)
    path.parent.mkdir(parents=True)
    garbage = bytes(range(256)) * 64
    path.write_bytes(garbage)
    for opener in (db.open_catalogue, db.connect):
        with pytest.raises(db.CatalogueCorruptError):
            opener(path)
        assert path.read_bytes() == garbage
    assert sorted(p.name for p in path.parent.iterdir()) == ["catalogue.db"]


def test_valid_header_with_mangled_pages_is_corrupt_not_a_crash(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    path = db_path(tmp_path)
    data = bytearray(path.read_bytes())
    data[100:4096] = b"\xff" * (4096 - 100)
    path.write_bytes(bytes(data))
    mangled = path.read_bytes()
    with pytest.raises(db.CatalogueCorruptError):
        db.open_catalogue(path)
    assert path.read_bytes() == mangled


def test_zero_byte_file_is_an_empty_database_and_becomes_a_catalogue(tmp_path: Path) -> None:
    path = db_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.touch()
    conn = db.open_catalogue(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_directory_at_the_path(tmp_path: Path) -> None:
    path = db_path(tmp_path)
    (path / "inside").mkdir(parents=True)
    with pytest.raises(db.CatalogueUnavailableError):
        db.open_catalogue(path)
    assert [p.name for p in path.iterdir()] == ["inside"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_read_only_parent(tmp_path: Path) -> None:
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        with pytest.raises(db.CatalogueUnavailableError):
            db.open_catalogue(parent / "catalogue.db")
        with pytest.raises(db.CatalogueUnavailableError):
            db.open_catalogue(parent / "sub" / "catalogue.db")
        assert list(parent.iterdir()) == []
    finally:
        parent.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_existing_catalogue_in_a_read_only_directory_is_unavailable_and_unchanged(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    path = db_path(tmp_path)
    for leftover in path.parent.glob("catalogue.db-*"):
        leftover.unlink()
    before = path.read_bytes()
    path.parent.chmod(0o500)
    try:
        with pytest.raises(db.CatalogueError):
            db.open_catalogue(path)
        assert path.read_bytes() == before
    finally:
        path.parent.chmod(0o700)


def test_every_catalogue_error_is_a_catalogue_error() -> None:
    for cls in (db.SchemaTooNewError, db.CatalogueBusyError, db.CatalogueCorruptError,
                db.CatalogueUnavailableError, db.ScanInProgressError):  # fmt: skip
        assert issubclass(cls, db.CatalogueError)
    assert db.ScanInProgressError(41).pid == 41


def test_split_statements_respects_strings_comments_and_refuses_a_dangling_tail() -> None:
    script = "CREATE TABLE a(x TEXT DEFAULT ';'); -- not; a statement\n"
    script += "CREATE TABLE b(y); CREATE TABLE c(z);\n-- end\n"
    statements = list(split_statements(script))
    assert len(statements) == 3 and statements[0].startswith("CREATE TABLE a")
    with pytest.raises(ValueError):
        list(split_statements("CREATE TABLE a(x); CREATE TABLE b("))
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("BEGIN")
    run_script(conn, script)
    assert conn.in_transaction  # unlike executescript, the caller's transaction is still open
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
