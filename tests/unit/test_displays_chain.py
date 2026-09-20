"""Chain resolution of ``scanner/displays.py``: probe order (rulings Q4/Q5), runners, merge, the reason."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from src.capability.reasons import ReasonCode, render
from src.scanner import displays as mod
from src.scanner.displays import (
    Display,
    DisplayDetection,
    DisplaySource,
    DrmDisplayProbe,
    XrandrProbe,
    default_runner,
    detect,
    has_session,
    merge_gdk_drm,
    parse_declared,
    service_probes,
    subprocess_runner,
)

FAKEROOTS = Path(__file__).resolve().parent.parent / "fakeroot"
XRANDR_TEXT = (
    "Screen 0: minimum 320 x 200, current 1080 x 1920, maximum 16384 x 16384\n"
    "eDP-1 connected primary 1080x1920+0+0 left (normal left inverted right x axis y axis) 344mm x 194mm\n"
    "   1920x1080     60.01*+\n"
)


class FakeProbe:
    def __init__(
        self,
        source: DisplaySource,
        displays: Sequence[Display] = (),
        *,
        detail: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.source = source
        self._displays = tuple(displays)
        self._error = error
        self.calls = 0
        if detail is not None:
            self.last_detail = detail

    def probe(self) -> tuple[Display, ...]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._displays


class FakeRunner:
    def __init__(self, result: str | None) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(self, argv: Sequence[str], timeout: float) -> str | None:
        self.calls.append((tuple(argv), timeout))
        return self.result


def gdk(name: str, width: int, height: int, **kwargs: object) -> Display:
    return Display(name, width, height, source=DisplaySource.GDK, **kwargs)  # type: ignore[arg-type]


def drm(name: str, width: int, height: int) -> Display:
    return Display(name, width, height, source=DisplaySource.DRM)


# ------------------------------------------------------------------------------------------- chain order


def test_session_puts_xrandr_first_then_drm() -> None:
    for env in (
        {"DISPLAY": ":0"},
        {"WAYLAND_DISPLAY": "wayland-0"},
        {"DISPLAY": ":1", "WAYLAND_DISPLAY": "w"},
    ):
        assert [p.source for p in service_probes(Path("/nowhere"), env, FakeRunner(None))] == [
            DisplaySource.XRANDR,
            DisplaySource.DRM,
        ]
        assert has_session(env)


def test_no_session_is_drm_only() -> None:
    for env in ({}, {"DISPLAY": ""}, {"XDG_SESSION_TYPE": "tty", "WAYLAND_DISPLAY": ""}):
        assert [p.source for p in service_probes(Path("/nowhere"), env)] == [DisplaySource.DRM]
        assert not has_session(env)


def test_in_a_session_xrandr_wins_and_drm_is_not_consulted() -> None:
    runner = FakeRunner(XRANDR_TEXT)
    detection = detect(service_probes(FAKEROOTS / "drm-one-panel", {"DISPLAY": ":0"}, runner))
    assert detection.displays == (Display("eDP-1", 1080, 1920, 1.0, True, DisplaySource.XRANDR),)
    assert [(a.source, a.ok) for a in detection.attempts] == [(DisplaySource.XRANDR, True)]
    assert detection.reason is None
    assert runner.calls == [(("xrandr", "--current"), 2.0)]


def test_in_a_session_drm_answers_when_xrandr_fails() -> None:
    detection = detect(service_probes(FAKEROOTS / "drm-one-panel", {"DISPLAY": ":0"}, FakeRunner(None)))
    assert [(d.name, d.width, d.height, d.source) for d in detection.displays] == [
        ("eDP-1", 1920, 1080, DisplaySource.DRM)
    ]
    assert [(a.source, a.ok) for a in detection.attempts] == [
        (DisplaySource.XRANDR, False),
        (DisplaySource.DRM, True),
    ]


def test_headless_never_runs_a_subprocess() -> None:
    runner = FakeRunner(XRANDR_TEXT)
    detection = detect(service_probes(FAKEROOTS / "drm-laptop-external", {}, runner))
    assert runner.calls == []
    assert {d.source for d in detection.displays} == {DisplaySource.DRM}


def test_first_non_empty_probe_wins_and_later_probes_are_not_run() -> None:
    empty = FakeProbe(DisplaySource.XRANDR)
    winner = FakeProbe(DisplaySource.DRM, [drm("DP-1", 2560, 1440)])
    never = FakeProbe(DisplaySource.XRANDR, [Display("X", 800, 600)])
    detection = detect([empty, winner, never])
    assert (empty.calls, winner.calls, never.calls) == (1, 1, 0)
    assert [d.name for d in detection.displays] == ["DP-1"]
    assert [a.detail for a in detection.attempts] == ["no display found", "DP-1 2560x1440"]


def test_raising_probe_is_a_failed_attempt() -> None:
    boom = FakeProbe(DisplaySource.GDK, error=RuntimeError("no\ndisplay " + "x" * 400))
    detection = detect([boom, FakeProbe(DisplaySource.DRM, [drm("DP-1", 1920, 1080)], detail="fine")])
    first, second = detection.attempts
    assert (first.source, first.ok) == (DisplaySource.GDK, False)
    assert first.detail.startswith("RuntimeError: no display")
    assert "\n" not in first.detail and len(first.detail) <= 240
    assert (second.ok, second.detail) == (True, "fine")


# ---------------------------------------------------------------------------------------------- declared


def test_declared_are_appended_and_same_size_is_dropped() -> None:
    probe = FakeProbe(DisplaySource.DRM, [drm("eDP-1", 1920, 1080)])
    detection = detect([probe], parse_declared("1920x1080,3840x2160"))
    assert [(d.name, d.width, d.source) for d in detection.displays] == [
        ("eDP-1", 1920, DisplaySource.DRM),
        ("declared-2", 3840, DisplaySource.DECLARED),
    ]
    assert detection.attempts[-1].source is DisplaySource.DECLARED
    assert detection.attempts[-1].detail == "2 declared, 1 added as targets"


def test_declared_alone_is_a_detection_with_a_primary() -> None:
    detection = detect([FakeProbe(DisplaySource.DRM)], parse_declared("3840x2160,1920x1080"))
    assert [(d.name, d.primary) for d in detection.displays] == [("declared-1", True), ("declared-2", False)]
    assert detection.reason is None


def test_declared_with_duplicate_size_or_name_is_dropped() -> None:
    declared = [Display("a", 1000, 1000), Display("a", 1200, 1200), Display("b", 1000, 1000)]
    assert [(d.name, d.width) for d in detect([], declared).displays] == [("a", 1000)]


# ----------------------------------------------------------------------------------------------- primary


def test_exactly_one_primary_first_flagged_wins() -> None:
    probe = FakeProbe(
        DisplaySource.GDK,
        [gdk("A", 800, 600), gdk("B", 1024, 768, primary=True), gdk("C", 1280, 720, primary=True)],
    )
    assert [d.primary for d in detect([probe]).displays] == [False, True, False]


def test_first_detected_is_primary_when_none_is_flagged() -> None:
    probe = FakeProbe(DisplaySource.XRANDR, [Display("A", 800, 600), Display("B", 1024, 768)])
    assert [d.primary for d in detect([probe], parse_declared("640x480")).displays] == [True, False, False]


def test_a_probe_naming_a_connector_twice_is_deduplicated() -> None:
    probe = FakeProbe(DisplaySource.GDK, [gdk("A", 800, 600), gdk("A", 1024, 768)])
    assert [(d.name, d.width) for d in detect([probe]).displays] == [("A", 800)]


# ------------------------------------------------------------------------------------------ merge (Q5)


def test_merge_takes_drm_size_in_gdk_orientation() -> None:
    merged, notes = merge_gdk_drm(
        [
            gdk("eDP-1", 3840, 2160, scale=2.0, primary=True),  # 2880x1800 panel at 1.5x, over-reported
            gdk("HDMI-A-1", 1200, 2000),  # rotated, over-reported
            gdk("DP-1", 1920, 1080),  # agrees
            gdk("DP-9", 1280, 720),  # DRM does not know it
            gdk("DP-3", 1000, 1000),  # square: no orientation to take
        ],
        [
            drm("eDP-1", 2880, 1800),
            drm("HDMI-A-1", 1920, 1080),
            drm("DP-1", 1920, 1080),
            drm("DP-3", 1024, 768),
            drm("DP-3", 640, 480),
            drm("DP-7", 640, 480),
        ],
    )
    assert merged == (
        gdk("eDP-1", 2880, 1800, scale=2.0, primary=True),
        gdk("HDMI-A-1", 1080, 1920),
        gdk("DP-1", 1920, 1080),
        gdk("DP-9", 1280, 720),
        gdk("DP-3", 1024, 768),
    )
    assert notes == (
        "eDP-1: gdk 3840x2160 -> drm 2880x1800",
        "HDMI-A-1: gdk 1200x2000 -> drm 1080x1920",
        "DP-3: gdk 1000x1000 -> drm 1024x768",
    )


def test_merge_keeps_a_rotated_display_that_agrees() -> None:
    merged, notes = merge_gdk_drm([gdk("DP-1", 1080, 1920)], [drm("DP-1", 1920, 1080)])
    assert (merged, notes) == ((gdk("DP-1", 1080, 1920),), ())


def test_detect_reconciles_gdk_with_a_drm_probe_in_the_chain_and_records_both() -> None:
    gdk_probe = FakeProbe(DisplaySource.GDK, [gdk("eDP-1", 3840, 2160, scale=2.0)])
    xrandr_probe = FakeProbe(DisplaySource.XRANDR, [Display("eDP-1", 1, 1)])
    drm_probe = FakeProbe(DisplaySource.DRM, [drm("eDP-1", 2880, 1800)], detail="eDP-1 2880x1800")
    detection = detect([gdk_probe, xrandr_probe, drm_probe])
    assert detection.displays == (gdk("eDP-1", 2880, 1800, scale=2.0, primary=True),)
    assert xrandr_probe.calls == 0
    assert [(a.source, a.ok) for a in detection.attempts] == [
        (DisplaySource.GDK, True),
        (DisplaySource.DRM, True),
    ]
    assert detection.attempts[1].detail == "eDP-1 2880x1800; eDP-1: gdk 3840x2160 -> drm 2880x1800"


def test_detect_gdk_agreeing_with_drm_or_without_drm_is_untouched() -> None:
    displays = [gdk("eDP-1", 1920, 1080, primary=True)]
    agreeing = detect(
        [FakeProbe(DisplaySource.GDK, displays), FakeProbe(DisplaySource.DRM, [drm("eDP-1", 1920, 1080)])]
    )
    assert agreeing.displays == tuple(displays)
    assert len(agreeing.attempts) == 2
    alone = detect([FakeProbe(DisplaySource.GDK, displays), FakeProbe(DisplaySource.XRANDR)])
    assert alone.displays == tuple(displays)
    assert len(alone.attempts) == 1
    failing_drm = detect(
        [FakeProbe(DisplaySource.GDK, displays), FakeProbe(DisplaySource.DRM, error=OSError("x"))]
    )
    assert failing_drm.displays == tuple(displays)
    assert [a.ok for a in failing_drm.attempts] == [True, False]


# ------------------------------------------------------------------------------------------------ reason


def test_display_not_detected_shape_and_rendering() -> None:
    detection = detect(service_probes(FAKEROOTS / "drm-none", {"DISPLAY": ":0"}, FakeRunner(None)))
    assert detection.displays == ()
    reason = detection.reason
    assert reason is not None
    assert reason.code is ReasonCode.DISPLAY_NOT_DETECTED
    assert reason.remedy == "--display WxH"
    assert reason.evidence == tuple((a.source.value, a.detail) for a in detection.attempts)
    assert [key for key, _value in reason.evidence] == ["xrandr", "drm"]
    assert all(value and "\n" not in value and len(value) <= 240 for _key, value in reason.evidence)
    message = render(reason)
    assert "xrandr: xrandr --current: not installed, failed or timed out" in message
    assert "--display" in message


def test_headless_garbage_tree_still_renders() -> None:
    detection = detect(service_probes(FAKEROOTS / "drm-garbage", {}))
    assert detection.reason is not None
    assert "{" not in render(detection.reason)


def test_no_probes_at_all_still_yields_renderable_evidence() -> None:
    detection = detect([])
    assert detection == DisplayDetection((), (), detection.reason)
    assert detection.reason is not None
    assert detection.reason.evidence == (("probes", "none configured"),)
    assert render(detection.reason)


def test_reason_is_set_exactly_when_nothing_was_found() -> None:
    assert detect([FakeProbe(DisplaySource.DRM, [drm("A", 800, 600)])]).reason is None
    assert detect([FakeProbe(DisplaySource.DRM)]).reason is not None


# ------------------------------------------------------------------------------------------ xrandr probe


@pytest.mark.parametrize(
    ("env", "output", "detail"),
    [
        ({"DISPLAY": ":0"}, None, "xrandr --current: not installed, failed or timed out"),
        (
            {"DISPLAY": ":0"},
            "Can't open display",
            "xrandr --current: no connected output with a current mode",
        ),
        ({"DISPLAY": ":0"}, XRANDR_TEXT, "eDP-1 1080x1920"),
        ({"WAYLAND_DISPLAY": "wayland-0"}, XRANDR_TEXT, "DISPLAY is not set"),
    ],
)
def test_xrandr_probe_details(env: dict[str, str], output: str | None, detail: str) -> None:
    probe = XrandrProbe(env, FakeRunner(output))
    displays = probe.probe()
    assert probe.last_detail == detail
    assert bool(displays) == (detail == "eDP-1 1080x1920")


def test_xrandr_probe_survives_a_raising_runner() -> None:
    def run(argv: Sequence[str], timeout: float) -> str | None:
        raise TimeoutError("slow")

    probe = XrandrProbe({"DISPLAY": ":0"}, run)
    assert probe.probe() == ()
    assert probe.last_detail == "TimeoutError: slow"


# ------------------------------------------------------------------------------------ subprocess runner


class Recorder:
    """Stands in for ``subprocess.run`` so no test executes a real binary."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.args: list[str] = []
        self.kwargs: dict[str, object] = {}

    def __call__(self, args: list[str], **kwargs: object) -> object:
        self.args, self.kwargs = args, kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def patch_run(
    monkeypatch: pytest.MonkeyPatch, result: object, which: str | None = "/usr/bin/xrandr"
) -> Recorder:
    recorder = Recorder(result)
    monkeypatch.setattr(mod.subprocess, "run", recorder)
    monkeypatch.setattr(mod.shutil, "which", lambda name, path=None: which)
    return recorder


def test_runner_uses_an_argument_vector_an_absolute_path_and_a_minimal_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = subprocess.CompletedProcess(["xrandr"], 0, stdout=XRANDR_TEXT.encode() + b"\xff", stderr=b"")
    recorder = patch_run(monkeypatch, done)
    env = {
        "DISPLAY": ":7",
        "XAUTHORITY": "/run/user/1000/xauth",
        "LD_PRELOAD": "/evil.so",
        "LANG": "de_DE.UTF-8",
    }
    probe = XrandrProbe(env)
    assert [d.name for d in probe.probe()] == ["eDP-1"]
    assert recorder.args == ["/usr/bin/xrandr", "--current"]
    assert recorder.kwargs["env"] == {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LC_ALL": "C",
        "DISPLAY": ":7",
        "XAUTHORITY": "/run/user/1000/xauth",
    }
    assert recorder.kwargs["timeout"] == 2.0
    assert recorder.kwargs["stdin"] is subprocess.DEVNULL
    assert "shell" not in recorder.kwargs


@pytest.mark.parametrize(
    "result",
    [
        subprocess.TimeoutExpired(["xrandr"], 2.0),
        FileNotFoundError("gone"),
        PermissionError("no"),
        ValueError("embedded null byte"),
        subprocess.CompletedProcess(["xrandr"], 1, stdout=b"Can't open display", stderr=b""),
    ],
)
def test_runner_failures_become_none(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    patch_run(monkeypatch, result)
    assert subprocess_runner({})(["xrandr", "--current"], 2.0) is None


def test_runner_absent_binary_and_empty_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = patch_run(monkeypatch, AssertionError("must not run"), which=None)
    run = subprocess_runner({})
    assert run(["xrandr", "--current"], 2.0) is None
    assert run([], 2.0) is None
    assert recorder.args == []


def test_default_runner_passes_only_display_variables_of_this_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = subprocess.CompletedProcess(["xrandr"], 0, stdout=b"ok", stderr=b"")
    recorder = patch_run(monkeypatch, done)
    monkeypatch.setenv("DISPLAY", ":42")
    monkeypatch.delenv("XAUTHORITY", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/evil")
    assert default_runner(["xrandr"], 1.0) == "ok"
    assert recorder.kwargs["env"] == {"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C", "DISPLAY": ":42"}


# ------------------------------------------------------------------------------------------ real machine


@pytest.mark.skipif(
    os.environ.get("LINWP_REAL_PROBES") != "1", reason="opt-in: LINWP_REAL_PROBES=1 runs the real probes"
)
def test_real_probes_on_this_machine_do_not_raise() -> None:
    detection = detect(service_probes(Path("/"), os.environ))
    assert isinstance(detection, DisplayDetection)
    assert (detection.reason is None) == bool(detection.displays)
    assert isinstance(detect([DrmDisplayProbe()]), DisplayDetection)
