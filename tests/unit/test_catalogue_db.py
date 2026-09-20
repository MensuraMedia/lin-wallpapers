"""``catalogue/db.py``: connection policy, locking, rules, exclusion flags, display snapshots, settings."""

from __future__ import annotations

import ast
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from src.catalogue import db, ideal, queries
from src.catalogue.db import Change, ChangeFeed, ChangeKind
from src.catalogue.model import FlagDelta
from src.scanner import exclude
from src.scanner.displays import Display, DisplaySource
from src.scanner.exclude import BUILTIN_GROUPS, BuiltinGroup, Rule, RuleKind
from tests.unit.test_catalogue_support import FHD, UHD, add_image, db_path, detection, open_db, set_displays

HOME = "/home/u"
CODE_RULE = (
    "SELECT id FROM exclusion WHERE builtin = 1 AND group_id = "
    "(SELECT id FROM exclusion_group WHERE key = 'code') LIMIT 1"
)


def matcher_for(conn: sqlite3.Connection, *extra: Rule) -> exclude.Matcher:
    rules, groups = db.load_rules(conn)
    return exclude.compile_matcher([*rules, *extra], groups, includes=(), home=HOME)


def image_columns(conn: sqlite3.Connection, image_id: int) -> dict[str, object]:
    row = conn.execute("SELECT * FROM image WHERE id = ?", (image_id,)).fetchone()
    return {key: row[key] for key in row.keys() if key != "excluded_by"}  # noqa: SIM118


# ── connection policy ────────────────────────────────────────────────────────────────────────────────────


def test_write_connection_pragmas(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000 == db.BUSY_TIMEOUT_MS
    assert conn.execute("PRAGMA query_only").fetchone()[0] == 0
    assert conn.isolation_level is None and conn.row_factory is sqlite3.Row


def test_read_connection_is_query_only(tmp_path: Path) -> None:
    open_db(tmp_path).close()
    reader = db.connect(db_path(tmp_path), readonly=True)
    assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
    assert reader.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert reader.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    with pytest.raises(sqlite3.OperationalError):
        reader.execute("INSERT INTO setting(key, value) VALUES ('a', '1')")
    with pytest.raises(db.CatalogueError):
        db.set_setting(reader, "a", 1)


def test_read_connection_never_creates_a_file(tmp_path: Path) -> None:
    with pytest.raises(db.CatalogueUnavailableError):
        db.connect(tmp_path / "absent.db", readonly=True)
    assert list(tmp_path.iterdir()) == []


def test_open_catalogue_defaults_to_the_xdg_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    conn = db.open_catalogue()
    assert db.database_path(conn) == tmp_path / "xdg" / "lin-wallpapers" / "catalogue.db"


def test_paths_with_uri_metacharacters_open_the_right_file(tmp_path: Path) -> None:
    path = tmp_path / "we?ird #dir%41" / "cat&mode=memory.db"
    conn = db.open_catalogue(path)
    assert path.is_file() and db.database_path(conn) == path


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO ideal_pin(image_id, pinned) VALUES (12345, 'in')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO image(path, dir, name, probe_status) VALUES ('/a/b', '/a', 'b', 'bogus')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO display(name, width, height, source) VALUES ('x', 0, 1080, 'drm')")
    image_id = add_image(conn, "/p/a.jpg")
    ideal.set_pin(conn, image_id, "in")
    conn.execute("DELETE FROM image WHERE id = ?", (image_id,))
    assert conn.execute("SELECT count(*) FROM ideal_pin").fetchone()[0] == 0  # cascades


def test_probe_status_accepts_too_large_with_null_dimensions(tmp_path: Path) -> None:  # ruling Q10a
    conn = open_db(tmp_path)
    image_id = add_image(conn, "/p/bomb.png", None, None, probe_status="too_large")
    row = queries.get_image(conn, image_id)
    assert row is not None and (row.width, row.height, row.probe_status) == (None, None, "too_large")


def test_a_connection_cannot_be_shared_between_threads(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    errors: list[BaseException] = []

    def use() -> None:
        try:
            conn.execute("SELECT 1")
        except sqlite3.ProgrammingError as error:
            errors.append(error)

    worker = threading.Thread(target=use)
    worker.start()
    worker.join()
    assert len(errors) == 1


def test_read_connections_are_one_per_thread(tmp_path: Path) -> None:
    open_db(tmp_path).close()
    pool = db.ReadConnections(db_path(tmp_path))
    seen: dict[str, tuple[int, int]] = {}

    def work(name: str) -> None:
        first, second = pool.get(), pool.get()
        assert first.execute("PRAGMA query_only").fetchone()[0] == 1
        seen[name] = (id(first), id(second))
        if name != "keep":
            pool.close_current()

    threads = [threading.Thread(target=work, args=(f"t{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    mine = pool.get()
    assert all(a == b for a, b in seen.values())
    assert id(mine) == id(pool.get())
    pool.close()
    with pytest.raises(db.CatalogueError):
        pool.get()
    with pytest.raises(sqlite3.ProgrammingError):
        mine.execute("SELECT 1")  # closed


# ── transactions and locking ─────────────────────────────────────────────────────────────────────────────


def test_transaction_commits_rolls_back_and_nests(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    with db.transaction(conn):
        db.set_setting(conn, "a", 1)  # joins the open transaction
        assert conn.in_transaction
    assert not conn.in_transaction and db.get_setting(conn, "a", 0) == 1
    with pytest.raises(RuntimeError), db.transaction(conn):
        db.set_setting(conn, "a", 2)
        db.set_setting(conn, "b", 3)
        raise RuntimeError("abort")
    assert not conn.in_transaction
    assert (db.get_setting(conn, "a", 0), db.get_setting(conn, "b", 0)) == (1, 0)
    with pytest.raises(db.CatalogueError), db.transaction(conn):
        conn.execute("INSERT INTO ideal_pin(image_id, pinned) VALUES (1, 'sideways')")
    assert not conn.in_transaction


def test_locked_database_raises_busy_within_the_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder = open_db(tmp_path)
    monkeypatch.setattr(db, "BUSY_TIMEOUT_MS", 150)
    other = db.connect(db_path(tmp_path))
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO setting(key, value) VALUES ('held', '1')")
    started = time.monotonic()
    with pytest.raises(db.CatalogueBusyError):
        db.set_setting(other, "x", 1)
    assert time.monotonic() - started < 3.0
    assert not other.in_transaction
    assert db.get_setting(other, "held", 0) == 0  # WAL: readers are not blocked and see the committed state
    holder.execute("COMMIT")
    db.set_setting(other, "x", 1)
    assert db.get_setting(holder, "x", 0) == 1


def test_open_catalogue_of_an_up_to_date_database_needs_no_write_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder = open_db(tmp_path)
    monkeypatch.setattr(db, "BUSY_TIMEOUT_MS", 150)
    holder.execute("BEGIN IMMEDIATE")
    second = open_db(tmp_path)  # the GUI can open while `linwp scan` is mid-batch
    assert second.execute("SELECT count(*) FROM exclusion_group").fetchone()[0] == len(BUILTIN_GROUPS)
    holder.execute("ROLLBACK")


def test_scan_lock_contention_and_release(tmp_path: Path) -> None:
    open_db(tmp_path).close()
    path = db_path(tmp_path)
    with db.scan_lock(path):
        with pytest.raises(db.ScanInProgressError) as caught, db.scan_lock(path):
            pytest.fail("a second scanner got the lock")
        assert caught.value.pid == os.getpid()
    with db.scan_lock(path):
        pass
    assert path.with_name("catalogue.db.scanlock").stat().st_mode & 0o777 == 0o600


def test_recover_marks_unfinished_scans_interrupted(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    conn.execute("INSERT INTO scan(started, pid) VALUES (10, 4242)")
    conn.execute("INSERT INTO scan(started, finished, result) VALUES (5, 9, 'ok')")
    conn.close()
    reopened = open_db(tmp_path)
    assert [tuple(r) for r in reopened.execute("SELECT started, result FROM scan ORDER BY started")] == [
        (5, "ok"),
        (10, "interrupted"),
    ]
    assert db.recover(reopened) == 0
    changes = reopened.total_changes
    db.recover(reopened)
    assert reopened.total_changes == changes


def test_recover_leaves_a_live_scan_alone(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    conn.execute("INSERT INTO scan(started, pid) VALUES (10, 4242)")
    with db.scan_lock(db_path(tmp_path)):
        assert db.recover(conn) == 0
        open_db(tmp_path).close()
        assert conn.execute("SELECT result FROM scan").fetchone()[0] == "running"
    assert db.recover(conn) == 1


# ── built-in groups and rules ────────────────────────────────────────────────────────────────────────────


def test_seed_is_idempotent_and_keeps_user_toggles(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    groups = conn.execute("SELECT key, builtin, locked, enabled FROM exclusion_group ORDER BY id").fetchall()
    assert [g["key"] for g in groups] == [g.key for g in BUILTIN_GROUPS]
    assert all(g["builtin"] and g["enabled"] for g in groups)
    assert conn.execute("SELECT count(*) FROM exclusion WHERE builtin = 1").fetchone()[0] == sum(
        len(g.rules) for g in BUILTIN_GROUPS
    )
    db.set_group_enabled(conn, "games", False)
    rule_id = conn.execute(CODE_RULE).fetchone()[0]
    db.set_rule_enabled(conn, rule_id, False)
    snapshot = [tuple(r) for r in conn.execute("SELECT * FROM exclusion ORDER BY id")]

    changes = conn.total_changes
    db.seed_builtins(conn, BUILTIN_GROUPS)
    assert conn.total_changes == changes  # nothing to do → no write, no write lock
    conn.close()
    conn = open_db(tmp_path)
    assert [tuple(r) for r in conn.execute("SELECT * FROM exclusion ORDER BY id")] == snapshot
    assert conn.execute("SELECT enabled FROM exclusion_group WHERE key = 'games'").fetchone()[0] == 0
    assert conn.execute("SELECT enabled FROM exclusion WHERE id = ?", (rule_id,)).fetchone()[0] == 0


def test_seed_follows_a_changed_builtin_table(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    db.set_group_enabled(conn, "games", False)
    changed = tuple(
        BuiltinGroup(g.key, "Games, renamed", g.locked, ((RuleKind.PATTERN, "**/newgames/**"),))
        if g.key == "games" else g
        for g in BUILTIN_GROUPS
    )  # fmt: skip
    db.seed_builtins(conn, changed)
    group = conn.execute("SELECT id, name, enabled FROM exclusion_group WHERE key = 'games'").fetchone()
    assert (group["name"], group["enabled"]) == ("Games, renamed", 0)
    values = [r[0] for r in conn.execute("SELECT value FROM exclusion WHERE group_id = ?", (group["id"],))]
    assert values == ["**/newgames/**"]


def test_locked_group_cannot_be_switched_off_by_any_route(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    locked = conn.execute("SELECT id, key, name FROM exclusion_group WHERE locked = 1").fetchone()
    assert locked["key"] == "system"
    rule_id = conn.execute("SELECT id FROM exclusion WHERE group_id = ?", (locked["id"],)).fetchone()[0]
    for call in (
        lambda: db.set_group_enabled(conn, "system", False),
        lambda: db.set_group_enabled(conn, locked["name"], False),
        lambda: db.set_rule_enabled(conn, rule_id, False),
        lambda: db.remove_rule(conn, rule_id),
        lambda: db.add_rule(conn, RuleKind.FOLDER, "/opt/x", group="system", root=None),
    ):
        with pytest.raises(db.CatalogueError):
            call()
    # tampering is healed by the next seed
    conn.execute("UPDATE exclusion_group SET enabled = 0 WHERE key = 'system'")
    conn.execute("UPDATE exclusion SET enabled = 0 WHERE id = ?", (rule_id,))
    db.seed_builtins(conn, BUILTIN_GROUPS)
    assert conn.execute("SELECT enabled FROM exclusion_group WHERE key = 'system'").fetchone()[0] == 1
    assert conn.execute("SELECT enabled FROM exclusion WHERE id = ?", (rule_id,)).fetchone()[0] == 1


def test_group_toggle_unknown_group(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    with pytest.raises(db.CatalogueError):
        db.set_group_enabled(conn, "no such group'; DROP TABLE exclusion;--", False)
    assert conn.execute("SELECT count(*) FROM exclusion").fetchone()[0] > 0


def test_add_rule_identity_with_nulls_groups_roots_and_validation(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    first = db.add_rule(conn, RuleKind.FOLDER, "/data/scans", group=None, root=None, now=7, note="n")
    assert db.add_rule(conn, RuleKind.FOLDER, "/data/scans", group=None, root=None) == first
    with pytest.raises(sqlite3.IntegrityError):  # the expression index treats NULL volume/root as equal
        conn.execute("INSERT INTO exclusion(kind, value) VALUES ('folder', '/data/scans')")
    conn.execute("INSERT INTO root(path, kind) VALUES ('/data', 'user')")
    scoped = db.add_rule(conn, RuleKind.FOLDER, "/data/scans", group=None, root="/data")
    on_volume = db.add_rule(conn, RuleKind.FOLDER, "scans", group=None, root=None, volume_id="UUID-1")
    assert len({first, scoped, on_volume}) == 3
    with pytest.raises(db.CatalogueError):
        db.add_rule(conn, RuleKind.FOLDER, "/x/y", group=None, root="/not/a/root")

    in_group = db.add_rule(conn, RuleKind.PATTERN, "*.screenshot.png", group="Work documents", root=None)
    again = db.add_rule(conn, RuleKind.PATTERN, "IMG_E*.jpg", group="Work documents", root=None)
    rows = conn.execute("SELECT id, group_id FROM exclusion WHERE id IN (?, ?)", (in_group, again)).fetchall()
    assert rows[0]["group_id"] == rows[1]["group_id"] is not None
    assert conn.execute("SELECT builtin, key FROM exclusion_group WHERE name = 'Work documents'").fetchone()[
        :
    ] == (0, None)

    for kind, value in (
        (RuleKind.FOLDER, "/"),
        (RuleKind.PATTERN, "**"),
        (RuleKind.PATTERN, ""),
        (RuleKind.PATTERN, "a\x00b"),
    ):
        with pytest.raises(exclude.PatternError):
            db.add_rule(conn, kind, value, group=None, root=None)

    file_rule = db.add_rule(conn, RuleKind.FILE, "/p/id-card.jpg", group=None, root=None, device=5, inode=99)
    folder_rule = db.add_rule(conn, RuleKind.FOLDER, "/p/private", group=None, root=None, device=5, inode=100)
    stored = {
        r["id"]: (r["device"], r["inode"]) for r in conn.execute("SELECT id, device, inode FROM exclusion")
    }
    assert stored[file_rule] == (5, 99) and stored[folder_rule] == (None, None)


def test_remove_and_toggle_user_rules(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    rule = db.add_rule(conn, RuleKind.FOLDER, "/data/scans", group=None, root=None)
    db.set_rule_enabled(conn, rule, False)
    rules, _groups = db.load_rules(conn)
    assert next(r for r in rules if r.id == rule).enabled is False
    db.remove_rule(conn, rule)
    with pytest.raises(db.CatalogueError):
        db.remove_rule(conn, rule)
    with pytest.raises(db.CatalogueError):
        db.set_rule_enabled(conn, rule, True)
    builtin = conn.execute(CODE_RULE).fetchone()[0]
    with pytest.raises(db.CatalogueError):
        db.remove_rule(conn, builtin)


def test_load_rules_round_trips_into_the_real_matcher(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    conn.execute("INSERT INTO root(path, kind) VALUES ('/data', 'user')")
    scoped = db.add_rule(conn, RuleKind.PATTERN, "*.tmp.jpg", group="mine", root="/data")
    rules, groups = db.load_rules(conn)
    mine = next(r for r in rules if r.id == scoped)
    assert (mine.kind, mine.value, mine.root, mine.enabled) == (RuleKind.PATTERN, "*.tmp.jpg", "/data", True)
    assert {g.key for g in groups if g.builtin} == {g.key for g in BUILTIN_GROUPS}
    assert next(g for g in groups if g.name == "mine").key == ""
    matcher = exclude.compile_matcher(rules, groups, includes=("/data",), home=HOME)
    hit = matcher.match_path("/data/a/x.tmp.jpg")
    assert hit is not None and hit.rule_id == scoped
    assert matcher.match_path("/elsewhere/x.tmp.jpg") is None
    node = matcher.match_path("/data/proj/node_modules/pkg/logo.png")
    assert node is not None and node.group_id is not None


# ── exclusion flags: never a delete ──────────────────────────────────────────────────────────────────────


def test_apply_exclusions_flags_and_clears_without_touching_other_columns(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    keep = add_image(
        conn, "/photos/keep.jpg", thumb_key="a" * 32, thumb_status="ok", score=77, badges='["4K"]'
    )
    scan = add_image(conn, "/photos/scans-2009/page.jpg", thumb_key="b" * 32, thumb_status="ok", score=12)
    deep = add_image(conn, "/photos/scans-2009/sub/deep.jpg")
    ideal.set_pin(conn, scan, "in")
    before = {i: image_columns(conn, i) for i in (keep, scan, deep)}
    assert db.apply_exclusions(conn, matcher_for(conn)) == FlagDelta(0, 0)

    rule = db.add_rule(conn, RuleKind.FOLDER, "/photos/scans-2009", group=None, root=None)
    assert db.apply_exclusions(conn, matcher_for(conn)) == FlagDelta(flagged=2, cleared=0)
    flags = dict(conn.execute("SELECT id, excluded_by FROM image").fetchall())
    assert flags == {keep: None, scan: rule, deep: rule}
    assert conn.execute("SELECT count(*) FROM image").fetchone()[0] == 3  # rows are never deleted
    assert {i: image_columns(conn, i) for i in (keep, scan, deep)} == before
    assert [r.name for r in queries.fetch_page(conn, queries.QuerySpec()).rows] == ["keep.jpg"]
    assert db.apply_exclusions(conn, matcher_for(conn)) == FlagDelta(0, 0)  # idempotent

    db.set_rule_enabled(conn, rule, False)
    assert db.apply_exclusions(conn, matcher_for(conn)) == FlagDelta(flagged=0, cleared=2)
    assert {i: image_columns(conn, i) for i in (keep, scan, deep)} == before  # thumbs, score, pins intact
    assert ideal.get_pin(conn, scan) == "in"
    assert len(queries.fetch_page(conn, queries.QuerySpec()).rows) == 3


def test_removing_a_rule_lets_an_overlapping_rule_take_over(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    image = add_image(conn, "/photos/scans/a.jpg")
    other = add_image(conn, "/photos/b.jpg")
    folder = db.add_rule(conn, RuleKind.FOLDER, "/photos/scans", group=None, root=None)
    pattern = db.add_rule(conn, RuleKind.PATTERN, "**/scans/**", group=None, root=None)
    db.apply_exclusions(conn, matcher_for(conn))
    assert conn.execute("SELECT excluded_by FROM image WHERE id = ?", (image,)).fetchone()[0] == folder
    db.remove_rule(conn, folder)  # ON DELETE SET NULL …
    assert conn.execute("SELECT excluded_by FROM image WHERE id = ?", (image,)).fetchone()[0] is None
    delta = db.apply_exclusions(conn, matcher_for(conn))  # … and the pattern takes over
    assert delta == FlagDelta(flagged=1, cleared=0)
    assert conn.execute("SELECT excluded_by FROM image WHERE id = ?", (image,)).fetchone()[0] == pattern
    assert conn.execute("SELECT excluded_by FROM image WHERE id = ?", (other,)).fetchone()[0] is None


def test_file_rule_follows_a_renamed_file_by_inode(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    image = add_image(conn, "/photos/renamed-since.jpg", device=5, inode=99)
    rule = db.add_rule(conn, RuleKind.FILE, "/photos/id-card.jpg", group=None, root=None, device=5, inode=99)
    assert db.apply_exclusions(conn, matcher_for(conn)) == FlagDelta(1, 0)
    assert conn.execute("SELECT excluded_by FROM image WHERE id = ?", (image,)).fetchone()[0] == rule


def test_group_toggle_reincludes_instantly(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    image = add_image(conn, "/home/u/proj/node_modules/pkg/hero.jpg")
    assert db.apply_exclusions(conn, matcher_for(conn)).flagged == 1
    db.set_group_enabled(conn, "code", False)
    assert db.apply_exclusions(conn, matcher_for(conn)) == FlagDelta(0, 1)
    assert conn.execute("SELECT excluded_by FROM image WHERE id = ?", (image,)).fetchone()[0] is None


def test_a_relative_path_row_is_data_not_a_crash(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    add_image(conn, "relative/looking.jpg")
    add_image(conn, "")
    assert db.apply_exclusions(conn, matcher_for(conn)) == FlagDelta(0, 0)


def test_preview_rule_counts_without_writing(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    for n in range(8):
        add_image(conn, f"/photos/thumbs/{n % 2}/t{n}.jpg")
    add_image(conn, "/photos/keep.jpg")
    already = db.add_rule(conn, RuleKind.FOLDER, "/photos/thumbs/1", group=None, root=None)
    db.apply_exclusions(conn, matcher_for(conn))
    changes = conn.total_changes
    candidate = Rule(id=-1, kind=RuleKind.PATTERN, value="**/thumbs/**")
    preview = db.preview_rule(conn, matcher_for(conn, candidate), -1)
    assert (preview.rule_id, preview.images, preview.folders) == (-1, 4, 1)
    assert preview.sample_paths == tuple(f"/photos/thumbs/0/t{n}.jpg" for n in (0, 2, 4, 6))
    assert conn.total_changes == changes and already > 0
    reader = db.connect(db_path(tmp_path), readonly=True)  # works on a query_only connection
    assert db.preview_rule(reader, matcher_for(reader, candidate), -1).images == 4
    wide = db.preview_rule(conn, matcher_for(conn, Rule(id=-2, kind=RuleKind.FOLDER, value="/photos")), -2)
    assert wide.images == 5 and len(wide.sample_paths) == db.PREVIEW_SAMPLE


# ── display snapshots ────────────────────────────────────────────────────────────────────────────────────


def test_display_snapshot_tracks_the_target_set(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    ids, changed = db.save_display_snapshot(conn, detection(FHD, UHD), 100)
    assert changed and ids == db.target_display_ids(conn) and len(ids) == 2
    assert db.save_display_snapshot(conn, detection(FHD, UHD), 200) == (ids, False)
    rows = queries.target_displays(conn)
    assert [(d.name, d.width, d.height, d.is_primary, d.source, d.first_seen, d.last_seen) for d in rows] == [
        ("eDP-1", 1920, 1080, True, "drm", 100, 200),
        ("HDMI-A-1", 3840, 2160, False, "drm", 100, 200),
    ]

    declared = Display("declared-1", 2560, 1440, source=DisplaySource.DECLARED)
    with_declared, changed = db.save_display_snapshot(conn, detection(FHD, declared), 300)
    assert changed and len(with_declared) == 2  # ruling Q3: a declared display is a target
    assert [d.name for d in queries.target_displays(conn)] == ["eDP-1", "declared-1"]
    assert conn.execute("SELECT connected FROM display WHERE name = 'HDMI-A-1'").fetchone()[0] == 0

    # a new mode on the same connector is a new target; the old row is kept as history, disconnected
    ids4, changed = db.save_display_snapshot(conn, detection(Display("eDP-1", 2880, 1800, primary=True)), 400)
    assert changed and len(ids4) == 1
    assert conn.execute("SELECT count(*) FROM display").fetchone()[0] == 4
    assert db.save_display_snapshot(conn, detection(), 500) == ([], True)
    back, changed = db.save_display_snapshot(conn, detection(FHD, UHD), 600)
    assert changed and back == ids  # same rows, same ids: pins and history stay attached


def test_display_snapshot_is_atomic_inside_a_writer_job(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    set_displays(conn, FHD)
    with pytest.raises(RuntimeError), db.transaction(conn):
        db.save_display_snapshot(conn, detection(UHD), 100)
        raise RuntimeError("writer job failed")
    assert [d.name for d in queries.target_displays(conn)] == ["eDP-1"]


# ── settings ─────────────────────────────────────────────────────────────────────────────────────────────


def test_default_settings_follow_the_rulings() -> None:
    assert db.DEFAULT_SETTINGS == {
        "scan.min_file_bytes": 65_536,  # Q6
        "scan.max_file_bytes": 268_435_456,
        "scan.min_long_edge": 1280,
        "ideal.threshold_pct": 16,  # Q1
        "thumbs.budget_bytes": 536_870_912,
        "scan.network_optin": [],
        "first_run_done": False,
    }
    assert db.DEFAULT_SETTINGS["ideal.threshold_pct"] == ideal.DEFAULT_THRESHOLD_PCT


def test_settings_round_trip_as_json_and_fall_back_safely(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    assert db.get_setting(conn, "ideal.threshold_pct", 16) == 16
    db.set_setting(conn, "ideal.threshold_pct", 20)
    db.set_setting(conn, "ideal.threshold_pct", 22)
    db.set_setting(conn, "scan.network_optin", ["UUID-1", "päth\n'; DROP TABLE setting;--"])
    db.set_setting(conn, "first_run_done", True)
    assert db.get_setting(conn, "ideal.threshold_pct", 16) == 22
    assert db.get_setting(conn, "scan.network_optin", [])[1] == "päth\n'; DROP TABLE setting;--"
    assert db.get_setting(conn, "first_run_done", False) is True
    assert db.get_setting(conn, "first_run_done", 0) == 0  # a bool is not an int here
    assert db.get_setting(conn, "ideal.threshold_pct", "text") == "text"  # wrong type → the default
    conn.execute("UPDATE setting SET value = '{not json' WHERE key = 'ideal.threshold_pct'")
    assert db.get_setting(conn, "ideal.threshold_pct", 16) == 16
    with pytest.raises(ValueError):
        db.set_setting(conn, "x", float("nan"))
    key = "k'; DROP TABLE setting;--"
    db.set_setting(conn, key, 1)
    assert db.get_setting(conn, key, 0) == 1


# ── change feed ──────────────────────────────────────────────────────────────────────────────────────────


def test_change_feed_fans_out_survives_a_bad_subscriber_and_unsubscribes() -> None:
    feed = ChangeFeed()
    got: list[Change] = []

    def bad(_change: Change) -> None:
        raise RuntimeError("subscriber bug")

    feed.subscribe(bad)
    unsubscribe = feed.subscribe(got.append)
    change = Change(ChangeKind.IMAGES_UPSERTED, (1, 2), scan_id=3)
    feed.emit(change)
    unsubscribe()
    unsubscribe()
    feed.emit(Change(ChangeKind.IDEAL_REBUILT))
    assert got == [change]
    assert {k.name for k in ChangeKind} == {
        "IMAGES_UPSERTED",
        "IMAGES_FLAGGED",
        "IDEAL_REBUILT",
        "DISPLAYS_CHANGED",
        "ROOTS_CHANGED",
        "RULES_CHANGED",
    }


def test_change_feed_from_many_threads() -> None:
    feed = ChangeFeed()
    got: list[Change] = []
    lock = threading.Lock()

    def collect(change: Change) -> None:
        with lock:
            got.append(change)

    feed.subscribe(collect)
    threads = [
        threading.Thread(target=lambda: [feed.emit(Change(ChangeKind.RULES_CHANGED)) for _ in range(50)])
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(got) == 400


# ── no formatted SQL ─────────────────────────────────────────────────────────────────────────────────────


MODULES = ["db.py", "ideal.py", "queries.py", "model.py", "migrations/__init__.py", "migrations/script.py",
           "migrations/m0001_initial.py"]  # fmt: skip


def _is_formatting(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.JoinedStr)
        or (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod | ast.Add))
        or (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
        )
    )


@pytest.mark.parametrize("module", MODULES)
def test_no_formatted_string_reaches_execute(module: str) -> None:
    """The first argument of every ``execute*`` call is a literal or a plain name — never built in place.

    The one audited exception is ``db._set_user_version``: PRAGMA takes no bound parameters, and the value
    is a range-checked ``int``.
    """
    tree = ast.parse((Path(db.__file__).parent / module).read_text(encoding="utf-8"))
    offenders: list[tuple[str, int]] = []
    for function in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(function):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args):
                continue
            if node.func.attr == "executescript":
                offenders.append((function.name, node.lineno))  # it would commit the caller's transaction
            if node.func.attr in {"execute", "executemany"} and any(
                map(_is_formatting, ast.walk(node.args[0]))
            ):
                offenders.append((function.name, node.lineno))
    assert offenders == []


def test_the_user_version_pragma_only_takes_a_checked_int(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    for bad in ("2; DROP TABLE image", 2.0, True, 0, -1, 10**9):
        with pytest.raises(ValueError):
            db._set_user_version(conn, bad)  # type: ignore[arg-type]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


# ── records and error mapping ────────────────────────────────────────────────────────────────────────────


def test_row_records_mirror_their_tables(tmp_path: Path) -> None:
    from dataclasses import fields

    from src.catalogue import model

    conn = open_db(tmp_path)
    conn.execute("INSERT INTO volume(volume_id, label, removable, online) VALUES ('U-1', 'USB', 1, 1)")
    conn.execute("INSERT INTO root(path, kind, volume_id) VALUES ('/media/usb', 'volume', 'U-1')")
    conn.execute("INSERT INTO scan(started, pid, root_ids) VALUES (5, 77, '[1]')")
    rule = db.add_rule(
        conn, RuleKind.FILE, "/media/usb/x.jpg", group=None, root="/media/usb", device=3, inode=4
    )
    set_displays(conn, FHD)
    add_image(conn, "/media/usb/a.jpg")
    pairs = (
        ("volume", model.volume_from_row, model.VolumeRow),
        ("root", model.root_from_row, model.RootRow),
        ("scan", model.scan_from_row, model.ScanRow),
        ("exclusion", model.rule_from_row, model.RuleRow),
        ("display", model.display_from_row, model.DisplayRow),
        ("image", model.image_from_row, model.ImageRow),
    )
    for table, build, record in pairs:
        row = conn.execute("SELECT * FROM " + table + " ORDER BY 1 DESC LIMIT 1").fetchone()  # constant names
        built = build(row)
        assert isinstance(built, record)
        assert [f.name for f in fields(record)] == list(row.keys()), table  # 1:1 with the columns, in order
    volume = model.volume_from_row(conn.execute("SELECT * FROM volume").fetchone())
    assert (volume.removable, volume.online, volume.network, volume.stable_inodes) == (
        True,
        True,
        False,
        True,
    )
    stored = model.rule_from_row(conn.execute("SELECT * FROM exclusion WHERE id = ?", (rule,)).fetchone())
    assert (stored.kind, stored.device, stored.inode, stored.builtin, stored.enabled) == (
        "file",
        3,
        4,
        False,
        True,
    )
    scan = model.scan_from_row(conn.execute("SELECT * FROM scan").fetchone())
    assert (scan.pid, scan.result, scan.found, scan.finished) == (77, "running", 0, None)


def test_sqlite_errors_map_onto_typed_errors() -> None:
    cases = {
        sqlite3.OperationalError("database is locked"): db.CatalogueBusyError,
        sqlite3.OperationalError("database table is locked"): db.CatalogueBusyError,
        sqlite3.OperationalError("unable to open database file"): db.CatalogueUnavailableError,
        sqlite3.OperationalError("attempt to write a readonly database"): db.CatalogueUnavailableError,
        sqlite3.OperationalError("database disk image is malformed"): db.CatalogueCorruptError,
        sqlite3.DatabaseError("file is not a database"): db.CatalogueCorruptError,
        sqlite3.IntegrityError("UNIQUE constraint failed"): db.CatalogueError,
        sqlite3.OperationalError("no such table: x"): db.CatalogueError,
        sqlite3.InterfaceError("bad parameter"): db.CatalogueError,
    }
    for error, expected in cases.items():
        assert type(db.translate_error(error)) is expected, error


def test_in_memory_database_migrates_without_a_backup_or_a_path() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    assert db.database_path(conn) is None
    assert db.migrate(conn) == 1
    from src.catalogue.migrations import MIGRATIONS, Migration

    assert db.run_migrations(conn, (*MIGRATIONS, Migration(2, "noop", lambda _c: None))) == 2
    conn.execute("INSERT INTO scan(started) VALUES (1)")
    assert db.recover(conn) == 1


def test_add_rule_refuses_a_blank_group_name(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    with pytest.raises(db.CatalogueError):
        db.add_rule(conn, RuleKind.FOLDER, "/data/x", group="   ", root=None)
    assert conn.execute("SELECT count(*) FROM exclusion WHERE builtin = 0").fetchone()[0] == 0
