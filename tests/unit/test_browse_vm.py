"""P6-I — ``BrowseVM``: filter chips ↔ QuerySpec, segment default, thumbnails as bytes, feed coalescing."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from src.catalogue.db import Change, ChangeKind, apply_exclusions, load_rules
from src.scanner.displays import Display, DisplaySource
from src.scanner.exclude import RuleKind, compile_matcher
from src.viewmodels.browse_vm import BrowseVM, Orientation, Segment, ThumbPlaceholder
from src.viewmodels.sources_vm import SourcesVM
from tests.unit.test_services import add_library, make_services, run_scan, wait


def _scan_count(services: object) -> int:
    conn = services.reads.get()
    return int(conn.execute("SELECT count(*) FROM scan").fetchone()[0])


class _ManualScheduler:
    """Queues callbacks instead of running them, so a test can control delivery order."""

    def __init__(self) -> None:
        self.jobs: list[Callable[[], None]] = []

    def __call__(self, cb: Callable[[], None]) -> None:
        self.jobs.append(cb)


def test_selection_ops_change_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        vm = BrowseVM(services)
        seen: list[frozenset[int]] = []
        vm.add_observer(lambda state: seen.append(state.selection))

        vm.select(5)
        assert vm.state.selection == frozenset({5})
        vm.select(6)
        assert vm.state.selection == frozenset({5, 6})
        vm.deselect(5)
        assert vm.state.selection == frozenset({6})
        vm.toggle_selection(6)  # present → removed
        assert vm.state.selection == frozenset()
        vm.toggle_selection(7)  # absent → added
        assert vm.state.selection == frozenset({7})
        vm.clear_selection()
        assert vm.state.selection == frozenset()
        assert seen[-1] == frozenset()  # observers were notified of the change
        vm.close()
    finally:
        services.close()


def test_stale_generation_result_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manual = _ManualScheduler()
    services = make_services(tmp_path, monkeypatch, scheduler=manual)
    try:
        add_library(
            services, tmp_path / "lib", [("wide.jpg", (1600, 1000)), ("tall.jpg", (1000, 1600))]
        )
        run_scan(services)  # committed before the VM exists → no feed callbacks queued
        vm = BrowseVM(services)

        # Two refreshes, each fully computed before the next is issued, so their delivery callbacks
        # queue in order [landscape(gen n), portrait(gen n+1)] with the VM's generation now the newer.
        wait(vm.set_orientation(Orientation.LANDSCAPE))
        wait(vm.set_orientation(Orientation.PORTRAIT))
        assert len(manual.jobs) == 2

        # Deliver the newer result first, then the STALE one last. The stale-generation guard must drop
        # the landscape result; without it the last delivery would wrongly overwrite with landscape.
        manual.jobs[1]()  # portrait, current generation
        manual.jobs[0]()  # landscape, superseded → must be ignored
        assert [c.name for c in vm.state.cards] == ["tall.jpg"]
        vm.close()
    finally:
        services.close()


def test_on_page_shown_refreshes_only_when_data_version_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000))])
        run_scan(services)
        vm = BrowseVM(services)

        wait(vm.on_page_shown())  # first look establishes the baseline (and refreshes once)
        gen_after_baseline = vm._generation  # type: ignore[attr-defined]

        wait(vm.on_page_shown())  # nothing changed → must NOT refresh
        assert vm._generation == gen_after_baseline  # type: ignore[attr-defined]

        services.writer.submit(
            lambda c: c.execute("INSERT INTO root(path, kind, enabled) VALUES ('/tmp/y', 'user', 1)")
        ).result()
        wait(vm.on_page_shown())  # another connection wrote → must refresh
        assert vm._generation == gen_after_baseline + 1  # type: ignore[attr-defined]
        vm.close()
    finally:
        services.close()


def test_load_thumb_placeholder_reason_distinguishes_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000))])
        run_scan(services)
        vm = BrowseVM(services)
        wait(vm.refresh())
        image_id = vm.state.cards[0].id

        def set_row(missing: bool, thumb_key: str | None) -> None:
            services.writer.submit(
                lambda c: c.execute(
                    "UPDATE image SET missing = ?, thumb_key = ? WHERE id = ?",
                    (int(missing), thumb_key, image_id),
                )
            ).result()

        def reason_for(missing: bool, thumb_key: str | None) -> str:
            set_row(missing, thumb_key)
            got: list[object] = []
            wait(vm.load_thumb(image_id, got.append))
            assert isinstance(got[0], ThumbPlaceholder)
            return got[0].reason

        absent_key = "a" * 32  # a valid-shaped key with no file on disk → thumbs.read() is None
        # No thumb key at all: a missing drive says 'missing', a present-but-thumbless image says 'none'.
        assert reason_for(missing=True, thumb_key=None) == "missing"
        assert reason_for(missing=False, thumb_key=None) == "none"
        # Thumb key present but unreadable: 'missing' when offline, 'failed' otherwise.
        assert reason_for(missing=True, thumb_key=absent_key) == "missing"
        assert reason_for(missing=False, thumb_key=absent_key) == "failed"
        vm.close()
    finally:
        services.close()


def test_refresh_lists_all_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000)), ("two.jpg", (1600, 1000))])
        run_scan(services)
        vm = BrowseVM(services)
        wait(vm.refresh())
        assert vm.state.total == 2
        assert len(vm.state.cards) == 2
    finally:
        services.close()


def test_orientation_chip_maps_to_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(
            services, tmp_path / "lib", [("wide.jpg", (1600, 1000)), ("tall.jpg", (1000, 1600))]
        )
        run_scan(services)
        vm = BrowseVM(services)
        wait(vm.refresh())
        assert len(vm.state.cards) == 2

        wait(vm.set_orientation(Orientation.LANDSCAPE))
        assert [c.name for c in vm.state.cards] == ["wide.jpg"]

        wait(vm.set_orientation(Orientation.PORTRAIT))
        assert [c.name for c in vm.state.cards] == ["tall.jpg"]
    finally:
        services.close()


def test_segment_default_flips_once_ideal_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000))])
        run_scan(services)  # no display → nothing is ideal yet
        vm = BrowseVM(services)
        wait(vm.refresh())
        assert vm.state.segment == Segment.ALL.value

        services.scan.refresh_displays([Display("HDMI-1", 1600, 1000, source=DisplaySource.DECLARED)])
        wait(vm.refresh())
        assert vm.state.counts.ideal == 1
        assert vm.state.segment == Segment.IDEAL.value
    finally:
        services.close()


def test_exclude_removes_row_and_undo_restores_without_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        lib = tmp_path / "lib"
        add_library(services, lib, [("one.jpg", (1600, 1000)), ("two.jpg", (1600, 1000))])
        run_scan(services)
        sources = SourcesVM(services)
        browse = BrowseVM(services)
        wait(browse.refresh())
        assert browse.state.total == 2

        outcome_holder: list[object] = []
        wait(sources.add_rule("*one.jpg", cb=outcome_holder.append))
        wait(browse.refresh())
        assert [c.name for c in browse.state.cards] == ["two.jpg"]

        rule_id = outcome_holder[0].rule_id
        wait(sources.remove_rule(rule_id))
        wait(browse.refresh())
        assert browse.state.total == 2

        assert _scan_count(services) == 1  # exclude/undo never rescans
        browse.close()
    finally:
        services.close()


def test_exclude_image_drops_card_creates_file_rule_and_undo_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        lib = tmp_path / "lib"
        add_library(services, lib, [("one.jpg", (1600, 1000)), ("two.jpg", (1600, 1000))])
        run_scan(services)
        browse = BrowseVM(services)
        wait(browse.refresh())
        assert browse.state.total == 2
        target = next(card for card in browse.state.cards if card.name == "one.jpg")

        outcome: list[object] = []
        wait(browse.exclude_image(target.id, cb=outcome.append))
        wait(browse.refresh())
        assert [c.name for c in browse.state.cards] == ["two.jpg"]  # the excluded card left the grid
        assert outcome[0].ok and outcome[0].kind == "file"

        rules, _groups = load_rules(services.reads.get())
        file_rules = [rule for rule in rules if rule.kind is RuleKind.FILE]
        assert len(file_rules) == 1  # a single FILE rule was created
        assert file_rules[0].value.endswith("one.jpg")

        wait(browse.undo_exclusion(outcome[0].rule_id))
        wait(browse.refresh())
        assert browse.state.total == 2  # the row returned
        assert _scan_count(services) == 1  # exclude/undo never rescans
        browse.close()
    finally:
        services.close()


def test_exclude_image_pins_the_inode_so_a_rename_stays_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline claim: a FILE rule keeps ``device``/``inode`` so a renamed file stays excluded.

    Fails if ``exclude_image`` stops passing ``device=row.device, inode=row.inode`` to ``add_rule``:
    the matcher then has no inode to fall back on and the renamed row re-appears.
    """
    services = make_services(tmp_path, monkeypatch)
    try:
        lib = tmp_path / "lib"
        add_library(services, lib, [("one.jpg", (1600, 1000))])
        run_scan(services)
        browse = BrowseVM(services)
        wait(browse.refresh())
        target = browse.state.cards[0]

        # Give the row a real device/inode (the scan may not have populated them for a fixture).
        def stamp(conn: object) -> None:
            conn.execute(  # type: ignore[attr-defined]
                "UPDATE image SET device = 4242, inode = 9999 WHERE id = ?", (target.id,)
            )

        services.writer.submit(stamp).result()

        wait(browse.exclude_image(target.id))

        conn = services.reads.get()
        rules, groups = load_rules(conn)
        file_rules = [rule for rule in rules if rule.kind is RuleKind.FILE]
        assert len(file_rules) == 1
        # The rule carries the identity, and the matcher excludes by inode alone (a rename survives).
        assert file_rules[0].device == 4242 and file_rules[0].inode == 9999
        matcher = compile_matcher(rules, groups, includes=[str(lib)], home=str(Path.home()))
        assert matcher.match_inode(4242, 9999) is not None

        # End to end: rename the path (keeping device/inode), re-flag — the row stays excluded.
        def rename_and_reapply(conn2: object) -> None:
            conn2.execute(  # type: ignore[attr-defined]
                "UPDATE image SET path = ?, name = ? WHERE id = ?",
                (str(lib / "renamed.jpg"), "renamed.jpg", target.id),
            )
            fresh_rules, fresh_groups = load_rules(conn2)  # type: ignore[arg-type]
            matcher2 = compile_matcher(
                fresh_rules, fresh_groups, includes=[str(lib)], home=str(Path.home())
            )
            apply_exclusions(conn2, matcher2)  # type: ignore[arg-type]

        services.writer.submit(rename_and_reapply).result()
        excluded_by = services.reads.get().execute(
            "SELECT excluded_by FROM image WHERE id = ?", (target.id,)
        ).fetchone()[0]
        assert excluded_by == file_rules[0].id  # still excluded after the rename
        browse.close()
    finally:
        services.close()


def test_exclude_and_undo_refresh_the_grid_through_the_change_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No manual ``refresh()``: the card must leave on exclude and return on undo purely because the
    writer path emits ``RULES_CHANGED``. Fails if the ``feed.emit`` in exclude/undo is removed."""
    services = make_services(tmp_path, monkeypatch)
    try:
        lib = tmp_path / "lib"
        add_library(services, lib, [("one.jpg", (1600, 1000)), ("two.jpg", (1600, 1000))])
        run_scan(services)
        browse = BrowseVM(services)
        wait(browse.refresh())
        assert browse.state.total == 2
        target = next(card for card in browse.state.cards if card.name == "one.jpg")

        gone = threading.Event()
        back = threading.Event()

        def observe(state: object) -> None:
            names = [card.name for card in state.cards]  # type: ignore[attr-defined]
            if "one.jpg" not in names and "two.jpg" in names:
                gone.set()
            if "one.jpg" in names and "two.jpg" in names:
                back.set()

        browse.add_observer(observe)

        outcome: list[object] = []
        wait(browse.exclude_image(target.id, cb=outcome.append))  # no refresh() call here
        assert gone.wait(timeout=5.0), "the feed-driven refresh did not drop the excluded card"

        wait(browse.undo_exclusion(outcome[0].rule_id))  # again, rely on the emit, not a refresh()
        assert back.wait(timeout=5.0), "the feed-driven refresh did not restore the card"
        browse.close()
    finally:
        services.close()


def test_exclude_folder_drops_every_card_under_the_dir_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        lib = tmp_path / "lib"
        add_library(services, lib, [("a.jpg", (1600, 1000)), ("b.jpg", (1600, 1000))])
        run_scan(services)
        browse = BrowseVM(services)
        wait(browse.refresh())
        assert browse.state.total == 2
        first = browse.state.cards[0]

        first_run: list[object] = []
        wait(browse.exclude_folder(first.id, cb=first_run.append))
        wait(browse.refresh())
        assert browse.state.total == 0  # every card under the directory left the grid
        assert first_run[0].ok and first_run[0].kind == "folder"

        # Re-running the same exclusion is idempotent: the same rule id, still empty, one FOLDER rule.
        second_run: list[object] = []
        wait(browse.exclude_folder(first.id, cb=second_run.append))
        wait(browse.refresh())
        assert browse.state.total == 0
        assert second_run[0].rule_id == first_run[0].rule_id

        rules, _groups = load_rules(services.reads.get())
        assert len([rule for rule in rules if rule.kind is RuleKind.FOLDER and not rule.group_id]) == 1
        browse.close()
    finally:
        services.close()


def test_load_thumb_delivers_bytes_and_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000))])
        run_scan(services)
        vm = BrowseVM(services)
        wait(vm.refresh())
        image_id = vm.state.cards[0].id

        got: list[object] = []
        wait(vm.load_thumb(image_id, got.append))
        assert isinstance(got[0], (bytes, bytearray))

        missing: list[object] = []
        wait(vm.load_thumb(10_000, missing.append))
        assert isinstance(missing[0], ThumbPlaceholder)
    finally:
        services.close()


def test_change_feed_coalesces_a_burst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        pending: list[Callable[[], None]] = []

        def coalesce(cb: Callable[[], None]) -> None:
            pending.append(cb)

        vm = BrowseVM(services, coalesce=coalesce)
        before = vm._generation  # type: ignore[attr-defined]
        for _ in range(3):
            services.feed.emit(Change(ChangeKind.IMAGES_UPSERTED))
        assert len(pending) == 1  # three emits collapsed into one scheduled refresh

        pending[0]()  # the coalesced flush
        assert vm._generation == before + 1  # type: ignore[attr-defined]
        vm.close()
    finally:
        services.close()


def test_on_page_shown_notices_another_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000))])
        run_scan(services)
        vm = BrowseVM(services)
        wait(vm.on_page_shown())
        first = vm._data_version  # type: ignore[attr-defined]

        services.writer.submit(
            lambda c: c.execute("INSERT INTO root(path, kind, enabled) VALUES ('/tmp/x', 'user', 1)")
        ).result()
        wait(vm.on_page_shown())
        assert vm._data_version != first  # type: ignore[attr-defined]
    finally:
        services.close()
