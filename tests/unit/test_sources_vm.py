"""P6-I — ``SourcesVM``: roots, rules/groups, pattern preview, test-a-path, the displays strip."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.viewmodels.sources_vm import PathTest, PreviewResult, RuleOutcome, SourcesSnapshot, SourcesVM
from tests.unit.test_services import add_library, make_services, run_scan, wait


def _snapshot(vm: SourcesVM) -> SourcesSnapshot:
    wait(vm.refresh())
    assert vm.state is not None
    return vm.state


def test_root_mutators_change_state_through_the_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        vm = SourcesVM(services)
        lib = tmp_path / "lib"
        lib.mkdir()

        added: list[SourcesSnapshot] = []
        wait(vm.add_root(str(lib), cb=added.append))
        root = next(r for r in added[0].roots if r.path == str(lib))
        assert root.enabled is True and root.proposed is False and root.id is not None
        # It really reached the catalogue, not just VM state:
        stored = services.reads.get().execute(
            "SELECT enabled FROM root WHERE path = ?", (str(lib),)
        ).fetchone()
        assert stored is not None and stored["enabled"] == 1
        root_id = root.id

        wait(vm.set_root_enabled(root_id, False))
        assert vm.state is not None
        assert next(r for r in vm.state.roots if r.id == root_id).enabled is False

        wait(vm.remove_root(root_id))
        assert vm.state is not None
        assert all(r.id != root_id for r in vm.state.roots)
        gone = services.reads.get().execute(
            "SELECT id FROM root WHERE id = ?", (root_id,)
        ).fetchone()
        assert gone is None
    finally:
        services.close()


def test_refresh_lists_roots_and_builtin_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        lib = tmp_path / "lib"
        add_library(services, lib, [("one.jpg", (1600, 1000))])
        snapshot = _snapshot(SourcesVM(services))
        assert any(root.path == str(lib) and not root.proposed for root in snapshot.roots)
        assert any(group.key == "system" and group.locked for group in snapshot.groups)
    finally:
        services.close()


def test_displays_strip_empty_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        snapshot = _snapshot(SourcesVM(services))
        assert snapshot.displays.displays == ()
        assert snapshot.displays.reason_code == "DISPLAY_NOT_DETECTED"
        assert snapshot.displays.empty_text
    finally:
        services.close()


def test_add_rule_then_test_a_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        lib = tmp_path / "lib"
        add_library(services, lib, [("one.jpg", (1600, 1000)), ("two.jpg", (1600, 1000))])
        run_scan(services)
        vm = SourcesVM(services)

        outcome: list[RuleOutcome] = []
        wait(vm.add_rule("*one.jpg", cb=outcome.append))
        assert outcome and outcome[0].ok and outcome[0].rule_id is not None

        excluded: list[PathTest] = []
        wait(vm.test_path(str(lib / "one.jpg"), cb=excluded.append))
        assert excluded[0].scanned is False
        assert excluded[0].rule_id == outcome[0].rule_id

        scanned: list[PathTest] = []
        wait(vm.test_path(str(lib / "two.jpg"), cb=scanned.append))
        assert scanned[0].scanned is True
    finally:
        services.close()


def test_pattern_preview_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        lib = tmp_path / "lib"
        add_library(services, lib, [("one.jpg", (1600, 1000)), ("two.jpg", (1600, 1000))])
        run_scan(services)
        vm = SourcesVM(services)

        got: list[PreviewResult] = []
        wait(vm.preview("*one.jpg", cb=got.append))
        assert got[0].ok is True
        assert got[0].images == 1
        assert got[0].folders == 1
    finally:
        services.close()


def test_refused_pattern_surfaces_its_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        vm = SourcesVM(services)
        got: list[PreviewResult] = []
        wait(vm.preview("**", cb=got.append))
        assert got[0].ok is False
        assert got[0].error_code == "matches_everything"

        outcome: list[RuleOutcome] = []
        wait(vm.add_rule("**", cb=outcome.append))
        assert outcome[0].ok is False
        assert outcome[0].error_code == "matches_everything"
    finally:
        services.close()


def test_locked_group_toggle_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        vm = SourcesVM(services)
        outcome: list[RuleOutcome] = []
        wait(vm.set_group_enabled("system", False, cb=outcome.append))
        assert outcome[0].ok is False
        assert outcome[0].error_code == "CatalogueError"
    finally:
        services.close()
