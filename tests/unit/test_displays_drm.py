"""DRM sysfs probe (M1.1b): fixture trees under ``tests/fakeroot/drm-*`` and trees built in ``tmp_path``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.scanner.displays import Display, DisplaySource, DrmDisplayProbe, parse_drm_connector

FAKEROOTS = Path(__file__).resolve().parent.parent / "fakeroot"


def connector(root: Path, dirname: str, status: str, modes: str, enabled: str | None = "enabled") -> Path:
    base = root / "sys" / "class" / "drm" / dirname
    base.mkdir(parents=True)
    (base / "status").write_text(status + "\n")
    (base / "modes").write_text(modes)
    if enabled is not None:
        (base / "enabled").write_text(enabled + "\n")
    return base


def sizes(displays: tuple[Display, ...]) -> list[tuple[str, int, int, bool]]:
    return [(d.name, d.width, d.height, d.primary) for d in displays]


def test_one_panel() -> None:
    probe = DrmDisplayProbe(FAKEROOTS / "drm-one-panel")
    displays = probe.probe()
    assert displays == (Display("eDP-1", 1920, 1080, 1.0, True, DisplaySource.DRM),)
    assert probe.last_detail == "eDP-1 1920x1080"


def test_laptop_and_external_primary_is_the_builtin_panel() -> None:
    displays = DrmDisplayProbe(FAKEROOTS / "drm-laptop-external").probe()
    assert sizes(displays) == [("HDMI-A-1", 2560, 1440, False), ("eDP-1", 1920, 1200, True)]


def test_hidpi_is_just_pixels() -> None:
    (display,) = DrmDisplayProbe(FAKEROOTS / "drm-hidpi").probe()
    assert (display.width, display.height, display.scale) == (3840, 2400, 1.0)


def test_disabled_output_is_dropped_when_another_is_enabled_and_duplicates_collapse() -> None:
    probe = DrmDisplayProbe(FAKEROOTS / "drm-disabled-output")
    assert sizes(probe.probe()) == [("DP-2", 3840, 2160, True)]
    assert "eDP-1: connected but disabled" in probe.last_detail
    assert "card1-DP-2: duplicate of DP-2" in probe.last_detail


def test_nothing_connected() -> None:
    probe = DrmDisplayProbe(FAKEROOTS / "drm-none")
    assert probe.probe() == ()
    assert "3 connector(s), none usable" in probe.last_detail
    assert "\n" not in probe.last_detail


def test_garbage_tree_yields_nothing_and_says_why() -> None:
    probe = DrmDisplayProbe(FAKEROOTS / "drm-garbage")
    assert probe.probe() == ()
    detail = probe.last_detail
    assert "card0-eDP-1: unparsable mode" in detail
    assert "card0-HDMI-A-1: no modes" in detail
    assert "card0-DP-4: status unreadable" in detail
    assert len(detail) <= 240


def test_all_connected_outputs_count_when_none_is_enabled(tmp_path: Path) -> None:
    connector(tmp_path, "card0-HDMI-A-1", "connected", "1920x1080\n", enabled="disabled")
    connector(tmp_path, "card0-DP-1", "connected", "2560x1440\n", enabled=None)
    assert sizes(DrmDisplayProbe(tmp_path).probe()) == [
        ("DP-1", 2560, 1440, True),
        ("HDMI-A-1", 1920, 1080, False),
    ]


def test_virtual_connector_of_a_vm_counts(tmp_path: Path) -> None:
    connector(tmp_path, "card0-Virtual-1", "connected", "1280x800\n")
    assert sizes(DrmDisplayProbe(tmp_path).probe()) == [("Virtual-1", 1280, 800, True)]


def test_natural_order_of_connectors(tmp_path: Path) -> None:
    connector(tmp_path, "card0-DP-10", "connected", "1024x768\n")
    connector(tmp_path, "card0-DP-2", "connected", "800x600\n")
    assert [d.name for d in DrmDisplayProbe(tmp_path).probe()] == ["DP-2", "DP-10"]


def test_non_utf8_bytes_and_status_unknown(tmp_path: Path) -> None:
    base = connector(tmp_path, "card0-DP-1", "connected", "")
    (base / "modes").write_bytes(b"\xff\xfe\x00garbage\n1920x1080\n")
    connector(tmp_path, "card0-DP-2", "unknown", "1920x1080\n")
    bad_status = connector(tmp_path, "card0-DP-3", "connected", "1920x1080\n")
    (bad_status / "status").write_bytes(b"\xff\xff\n")
    probe = DrmDisplayProbe(tmp_path)
    assert probe.probe() == ()
    assert "card0-DP-1: unparsable mode" in probe.last_detail
    assert "DP-2" not in probe.last_detail  # not connected: no noise


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads through chmod 000")
def test_unreadable_files(tmp_path: Path) -> None:
    locked_modes = connector(tmp_path, "card0-DP-1", "connected", "1920x1080\n")
    locked_status = connector(tmp_path, "card0-DP-2", "connected", "1920x1080\n")
    connector(tmp_path, "card0-eDP-1", "connected", "1366x768\n")
    (locked_modes / "modes").chmod(0)
    (locked_status / "status").chmod(0)
    try:
        probe = DrmDisplayProbe(tmp_path)
        assert sizes(probe.probe()) == [("eDP-1", 1366, 768, True)]
        assert "card0-DP-1: modes unreadable" in probe.last_detail
        assert "card0-DP-2: status unreadable" in probe.last_detail
    finally:
        (locked_modes / "modes").chmod(0o644)
        (locked_status / "status").chmod(0o644)


def test_missing_sys_and_empty_drm_dir(tmp_path: Path) -> None:
    probe = DrmDisplayProbe(tmp_path)
    assert probe.probe() == ()
    assert "No such file" in probe.last_detail
    (tmp_path / "sys" / "class" / "drm").mkdir(parents=True)
    assert probe.probe() == ()
    assert probe.last_detail.endswith("no connectors")


def test_drm_path_that_is_a_file(tmp_path: Path) -> None:
    (tmp_path / "sys" / "class").mkdir(parents=True)
    (tmp_path / "sys" / "class" / "drm").write_text("not a directory")
    assert DrmDisplayProbe(tmp_path).probe() == ()


def test_probe_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = DrmDisplayProbe(tmp_path)

    def boom() -> tuple[tuple[Display, ...], str]:
        raise RuntimeError("kaputt\nzweite Zeile")

    monkeypatch.setattr(probe, "_probe", boom)
    assert probe.probe() == ()
    assert probe.last_detail == "RuntimeError: kaputt zweite Zeile"


def test_default_root_is_the_real_one() -> None:
    assert DrmDisplayProbe()._dir == Path("/sys/class/drm")


@pytest.mark.parametrize(
    ("dirname", "status", "enabled", "modes", "expected"),
    [
        ("card0-eDP-1", "connected\n", "enabled\n", "1920x1080\n1280x720\n", ("eDP-1", 1920, 1080)),
        ("card12-HDMI-A-1", " connected ", None, "3840x2160", ("HDMI-A-1", 3840, 2160)),
        ("card0-DP-1", "connected", "disabled", "1920x1080i\n", ("DP-1", 1920, 1080)),
        ("card0-DP-1", "disconnected", "disabled", "", None),
        ("card0-DP-1", "unknown", None, "1920x1080\n", None),
        ("card0-DP-1", "", None, "1920x1080\n", None),
        ("card0-DP-1", "connected", "enabled", "", None),
        ("card0-DP-1", "connected", "enabled", "\n1920x1080\n", None),
        ("card0-DP-1", "connected", "enabled", "x1080\n", None),
        ("card0-DP-1", "connected", "enabled", "0x1080\n", None),
        ("card0-DP-1", "connected", "enabled", "1920x40000\n", None),
        ("card0-Writeback-1", "connected", None, "1920x1080\n", None),
        ("card0", "connected", None, "1920x1080\n", None),
        ("renderD128", "connected", None, "1920x1080\n", None),
    ],
)
def test_parse_drm_connector(
    dirname: str, status: str, enabled: str | None, modes: str, expected: tuple[str, int, int] | None
) -> None:
    display = parse_drm_connector(dirname, status, enabled, modes)
    if expected is None:
        assert display is None
    else:
        assert display is not None
        assert (display.name, display.width, display.height) == expected
        assert (display.scale, display.primary, display.source) == (1.0, False, DisplaySource.DRM)
