"""P6-I — ``ScanVM``: start/cancel and progress observation, all on the injected scheduler."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.catalogue.ingest import ScanProgress
from src.scanner.displays import Display, DisplaySource
from src.viewmodels.scan_vm import ScanState, ScanVM
from tests.unit.test_services import add_library, make_services, wait


def _scan_count(services: object) -> int:
    conn = services.reads.get()
    return int(conn.execute("SELECT count(*) FROM scan").fetchone()[0])


def _progress(dirs: int) -> ScanProgress:
    return ScanProgress(
        scan_id=1,
        dirs=dirs,
        found=dirs,
        unchanged=0,
        probed=dirs,
        ideal=0,
        excluded=0,
        issues=0,
        walk_done=False,
        current_dir="",
    )


def test_progress_is_throttled_to_10hz(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        vm = ScanVM(services)
        seen: list[ScanState] = []
        vm.add_observer(seen.append)

        for i in range(50):  # a tight burst, all inside one 100 ms window
            vm.on_progress(_progress(i))

        assert len(seen) == 1  # coalesced: only the first of the burst is delivered
        assert seen[0].running is True
        assert seen[0].dirs == 0
    finally:
        services.close()


def test_construction_scans_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000))])
        vm = ScanVM(services)  # first-run consent lives in the page: constructing must not scan
        assert vm.state == ScanState()
        assert vm.running is False
        assert _scan_count(services) == 0
    finally:
        services.close()


def test_start_runs_a_scan_and_reports_final_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000)), ("two.jpg", (1600, 1000))])
        vm = ScanVM(services)
        seen: list[ScanState] = []
        vm.add_observer(seen.append)

        display = Display("HDMI-1", 1600, 1000, source=DisplaySource.DECLARED)
        wait(vm.start(declared=[display]))

        assert vm.state.running is False
        assert vm.state.result == "ok"
        assert vm.state.found == 2
        assert vm.state.ideal == 2  # both images are exactly the declared display's size
        assert any(state.running for state in seen)  # a running state was delivered first
        assert vm.state.displays and vm.state.displays[0].name == "HDMI-1"
        assert vm.state.reason_code is None
    finally:
        services.close()


def test_start_without_display_records_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000))])
        vm = ScanVM(services)

        wait(vm.start())  # no probes, no declared display

        assert vm.state.result == "ok"
        assert vm.state.reason_code == "DISPLAY_NOT_DETECTED"
        assert vm.state.displays == ()
    finally:
        services.close()


def test_start_is_a_no_op_while_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("one.jpg", (1600, 1000))])
        vm = ScanVM(services)
        # force the "already running" guard without a race: pretend a scan is in flight
        vm._state = ScanState(running=True)  # type: ignore[attr-defined]
        assert vm.start() is None
    finally:
        services.close()
