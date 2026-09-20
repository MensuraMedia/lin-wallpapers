"""Display detection: every scan measures this desktop before it judges an image (concept §5.2, M1.1b).

All probes return the same ``Display`` record, in **physical pixels after rotation**. This module is
service-side: no GTK, stdlib only. The GDK probe lives on the GUI side (``viewmodels/gdk_displays.py``)
and plugs in through the ``DisplayProbe`` protocol.

Chain (ruling Q4): inside a session (``DISPLAY`` or ``WAYLAND_DISPLAY`` set) ``xrandr --current`` leads,
because it knows the *current* mode and the rotation; DRM sysfs follows. Without a display server DRM
sysfs is the only probe. DRM reports the preferred mode of each connected connector and never claims a
rotation or a scale. Ruling Q5: when the GDK probe wins and a DRM probe is in the chain, a connector both
of them name gets DRM's pixel size in GDK's orientation (GDK over-reports under fractional scaling).

Nothing here raises out of ``detect()``: a probe that fails becomes a ``ProbeAttempt``, and when no display
is found the detection carries ``Reason(DISPLAY_NOT_DETECTED, …)`` so the scan can proceed and say why the
ideal segment is empty.

Everything that depends on the machine — the sysfs root, the environment, the subprocess runner — is
injected, so tests never see this machine's monitor, ``DISPLAY``, locale or installed tools.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from src.capability.reasons import Reason, ReasonCode

__all__ = [
    "REMEDY",
    "Display",
    "DisplayDetection",
    "DisplayProbe",
    "DisplaySource",
    "DisplaySpecError",
    "DrmDisplayProbe",
    "ProbeAttempt",
    "Runner",
    "XrandrProbe",
    "default_runner",
    "detect",
    "has_session",
    "merge_gdk_drm",
    "parse_declared",
    "parse_drm_connector",
    "parse_xrandr",
    "service_probes",
    "subprocess_runner",
]

REMEDY = "--display WxH"

DECLARED_MIN = 320
DECLARED_MAX = 16384
DECLARED_LIMIT = 8

_PROBED_MAX = 32768  # no connector reports more; anything larger is a garbage line
_DETAIL_MAX = 240
_READ_LIMIT = 65536
_OUTPUT_LIMIT = 262144
_XRANDR_TIMEOUT = 2.0
_SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
_PASSED_ENV = ("DISPLAY", "XAUTHORITY")


class DisplaySource(StrEnum):
    GDK = "gdk"
    DRM = "drm"
    XRANDR = "xrandr"
    DECLARED = "declared"


@dataclass(frozen=True)
class Display:
    """One target output. ``width`` × ``height`` are physical pixels after rotation; both > 0."""

    name: str
    width: int
    height: int
    scale: float = 1.0
    primary: bool = False
    source: DisplaySource = DisplaySource.DECLARED

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("display name is empty")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"display {self.name}: dimensions must be positive, got {self.width}x{self.height}"
            )
        if not self.scale > 0:
            raise ValueError(f"display {self.name}: scale must be positive, got {self.scale}")


@dataclass(frozen=True)
class ProbeAttempt:
    """Evidence: one per probe tried. ``detail`` is a short single line."""

    source: DisplaySource
    ok: bool
    detail: str


@dataclass(frozen=True)
class DisplayDetection:
    displays: tuple[Display, ...]
    attempts: tuple[ProbeAttempt, ...]
    reason: Reason | None
    """``Reason(DISPLAY_NOT_DETECTED, …, remedy="--display WxH")`` exactly when ``displays == ()``."""


class DisplayProbe(Protocol):
    """A way to measure the desktop. ``probe()`` returns ``()`` when it finds nothing.

    A probe should not raise, but ``detect()`` catches it if one does. A probe may also expose a
    ``last_detail: str`` attribute describing its latest ``probe()`` call; ``detect()`` copies it into the
    ``ProbeAttempt`` when present.
    """

    source: DisplaySource

    def probe(self) -> tuple[Display, ...]: ...


Runner = Callable[[Sequence[str], float], "str | None"]
"""``(argv, timeout_seconds) -> stdout`` — ``None`` when the binary is absent, fails or times out."""


class DisplaySpecError(ValueError):
    """A ``--display`` specification that cannot be used. ``spec`` is the offending part, ``problem`` why."""

    def __init__(self, spec: str, problem: str) -> None:
        super().__init__(f"invalid display {spec!r}: {problem}")
        self.spec = spec
        self.problem = problem


def _one_line(text: str, limit: int = _DETAIL_MAX) -> str:
    """``text`` as a short, printable single line — evidence ends up in messages and JSON."""
    flat = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _size(display: Display) -> str:
    return f"{display.width}x{display.height}"


# --------------------------------------------------------------------------------------------- DRM sysfs

_DRM_DIR = re.compile(r"^card(\d+)-(.+)$", re.ASCII)
_DRM_MODE = re.compile(r"^(\d{1,6})x(\d{1,6})", re.ASCII)
_DRM_BUILTIN = ("eDP", "LVDS", "DSI")
_WRITEBACK = "writeback connector"


def _drm_connector(dirname: str, status: str, modes: str) -> Display | str:
    """The display behind one connector directory, or the short reason it does not count."""
    match = _DRM_DIR.match(dirname)
    if match is None:
        return "not a connector"
    name = match.group(2)
    if name.startswith("Writeback"):
        return _WRITEBACK
    state = status.strip()
    if state != "connected":
        return _one_line(f"status {state or 'empty'}", 40)
    lines = modes.splitlines()
    if not lines or not lines[0].strip():
        return "no modes"
    mode = _DRM_MODE.match(lines[0].strip())
    if mode is None:
        return "unparsable mode"
    width, height = int(mode.group(1)), int(mode.group(2))
    if not (0 < width <= _PROBED_MAX and 0 < height <= _PROBED_MAX):
        return "implausible mode"
    return Display(name=name, width=width, height=height, source=DisplaySource.DRM)


def parse_drm_connector(dirname: str, status: str, enabled: str | None, modes: str) -> Display | None:
    """Pure: one ``/sys/class/drm/cardN-NAME`` directory's file contents → its display, or ``None``.

    Counts when ``status`` is ``connected`` and the first line of ``modes`` starts with ``WxH`` (the
    connector's preferred mode). Scale is 1.0 and ``primary`` is unset — DRM knows neither, nor rotation.
    ``enabled`` is accepted for symmetry with the directory but decides nothing for a single connector:
    the rule "if any connected connector is enabled, only those count" needs the whole set and lives in
    ``DrmDisplayProbe``.
    """
    del enabled
    result = _drm_connector(dirname, status, modes)
    return result if isinstance(result, Display) else None


def _read_text(path: Path) -> str | None:
    """At most 64 KiB of ``path``, decoded leniently; ``None`` when it cannot be read."""
    try:
        with path.open("rb") as handle:
            return handle.read(_READ_LIMIT).decode("utf-8", errors="replace")
    except OSError:
        return None


def _natural(text: str) -> tuple[tuple[int, str], ...]:
    """Sort key: digit runs compare as numbers, so ``DP-2`` precedes ``DP-10``."""
    parts = (part for part in re.split(r"([0-9]+)", text) if part)
    return tuple((int(part), "") if part[0] in "0123456789" else (-1, part) for part in parts)


class DrmDisplayProbe:
    """Reads ``<root>/sys/class/drm/card*-*/{status,enabled,modes}``. Needs no display server."""

    source = DisplaySource.DRM

    def __init__(self, root: Path = Path("/")) -> None:
        self._dir = Path(root) / "sys" / "class" / "drm"
        self.last_detail = ""

    def probe(self) -> tuple[Display, ...]:
        try:
            displays, detail = self._probe()
        except Exception as exc:
            displays, detail = (), f"{type(exc).__name__}: {exc}"
        self.last_detail = _one_line(detail)
        return displays

    def _probe(self) -> tuple[tuple[Display, ...], str]:
        try:
            dirnames = sorted(
                (entry.name for entry in self._dir.iterdir() if _DRM_DIR.match(entry.name)), key=_natural
            )
        except OSError as exc:
            return (), f"/sys/class/drm: {exc.strerror or type(exc).__name__}"
        found: dict[str, tuple[Display, bool]] = {}
        skipped: list[str] = []
        for dirname in dirnames:
            base = self._dir / dirname
            status = _read_text(base / "status")
            if status is None:
                skipped.append(f"{dirname}: status unreadable")
                continue
            modes = _read_text(base / "modes")
            result = _drm_connector(dirname, status, modes or "")
            if isinstance(result, str):
                # Disconnected and writeback connectors are the normal case: no noise in the evidence.
                if status.strip() == "connected" and result != _WRITEBACK:
                    skipped.append(f"{dirname}: {'modes unreadable' if modes is None else result}")
                continue
            if result.name in found:
                skipped.append(f"{dirname}: duplicate of {result.name}")
                continue
            enabled = _read_text(base / "enabled")
            found[result.name] = (result, enabled is not None and enabled.strip() == "enabled")
        if any(is_enabled for _display, is_enabled in found.values()):
            for name in [name for name, (_display, is_enabled) in found.items() if not is_enabled]:
                skipped.append(f"{name}: connected but disabled")
                del found[name]
        displays = sorted((display for display, _enabled in found.values()), key=lambda d: _natural(d.name))
        if not displays:
            seen = f"{len(dirnames)} connector(s), none usable" if dirnames else "no connectors"
            return (), "; ".join([f"/sys/class/drm: {seen}", *skipped])
        builtin = next((d for d in displays if d.name.startswith(_DRM_BUILTIN)), displays[0])
        marked = tuple(replace(d, primary=d is builtin) for d in displays)
        return marked, "; ".join([", ".join(f"{d.name} {_size(d)}" for d in marked), *skipped])


# ------------------------------------------------------------------------------------------------ xrandr

_XRANDR_OUTPUT = re.compile(
    r"^(?P<name>\S+) connected(?P<primary> primary)?"
    r"(?: (?P<w>\d{1,6})x(?P<h>\d{1,6})\+-?\d+\+-?\d+)?"
    r"(?: (?P<rotation>normal|left|inverted|right)\b)?",
    re.ASCII,
)
_XRANDR_MODE = re.compile(r"^\s+(\d{1,6})x(\d{1,6})\S*\s.*\*", re.ASCII)


def parse_xrandr(text: str) -> tuple[Display, ...]:
    """Pure: ``xrandr --current`` output → the connected outputs that are showing a picture.

    The ``WxH+X+Y`` geometry of an output line is already rotated, so it is the display's size as it
    stands. An output without geometry is connected but off and is skipped; disconnected outputs are
    ignored. When the current (``*``) mode, swapped for a left/right rotation, differs from the geometry,
    the framebuffer is scaled (``--scale``) and the mode is the physical size.
    """
    blocks: list[tuple[re.Match[str], list[tuple[int, int]]]] = []
    modes: list[tuple[int, int]] | None = None
    for line in text.splitlines():
        if line[:1] in (" ", "\t"):
            mode = _XRANDR_MODE.match(line)
            if modes is not None and mode is not None:
                modes.append((int(mode.group(1)), int(mode.group(2))))
            continue
        modes = None
        output = _XRANDR_OUTPUT.match(line)
        if output is not None and output.group("w") is not None:
            modes = []
            blocks.append((output, modes))

    displays: dict[str, Display] = {}
    for output, current_modes in blocks:
        width, height = int(output.group("w")), int(output.group("h"))
        if current_modes:
            sideways = output.group("rotation") in ("left", "right")
            width, height = current_modes[0][::-1] if sideways else current_modes[0]
        name = output.group("name")
        if 0 < width <= _PROBED_MAX and 0 < height <= _PROBED_MAX and name not in displays:
            displays[name] = Display(
                name, width, height, primary=output.group("primary") is not None, source=DisplaySource.XRANDR
            )
    return tuple(displays.values())


def subprocess_runner(env: Mapping[str, str]) -> Runner:
    """A ``Runner`` that executes argv — never a shell — under exactly ``env``.

    ``argv[0]`` is resolved to an absolute path on a fixed system ``PATH``; stdin is closed; the output is
    capped. Absent binary, non-zero exit, timeout and any OS error all yield ``None``.
    """
    child_env = dict(env)

    def run(argv: Sequence[str], timeout: float) -> str | None:
        if not argv:
            return None
        executable = shutil.which(argv[0], path=_SAFE_PATH)
        if executable is None:
            return None
        try:
            done = subprocess.run(
                [executable, *argv[1:]],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=child_env,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        if done.returncode != 0:
            return None
        return done.stdout[:_OUTPUT_LIMIT].decode("utf-8", errors="replace")

    return run


def _child_env(env: Mapping[str, str]) -> dict[str, str]:
    """The fixed minimal environment of a probe subprocess: ``DISPLAY``/``XAUTHORITY`` and nothing else."""
    child = {"PATH": _SAFE_PATH, "LC_ALL": "C"}
    child.update({key: env[key] for key in _PASSED_ENV if env.get(key)})
    return child


def default_runner(argv: Sequence[str], timeout: float) -> str | None:
    """The process-wide ``Runner``: ``subprocess_runner`` over this process's ``DISPLAY``/``XAUTHORITY``.

    ``XrandrProbe`` left with this default runs under the environment *it* was given instead.
    """
    return subprocess_runner(_child_env(os.environ))(argv, timeout)


class XrandrProbe:
    """Runs ``xrandr --current`` (no re-probe of the hardware) and parses it. Needs an X display."""

    source = DisplaySource.XRANDR

    def __init__(self, env: Mapping[str, str], run: Runner = default_runner) -> None:
        self._has_display = bool(env.get("DISPLAY"))
        self._run = subprocess_runner(_child_env(env)) if run is default_runner else run
        self.last_detail = ""

    def probe(self) -> tuple[Display, ...]:
        try:
            displays, detail = self._probe()
        except Exception as exc:
            displays, detail = (), f"{type(exc).__name__}: {exc}"
        self.last_detail = _one_line(detail)
        return displays

    def _probe(self) -> tuple[tuple[Display, ...], str]:
        if not self._has_display:
            return (), "DISPLAY is not set"
        text = self._run(("xrandr", "--current"), _XRANDR_TIMEOUT)
        if text is None:
            return (), "xrandr --current: not installed, failed or timed out"
        displays = parse_xrandr(text[:_OUTPUT_LIMIT])
        if not displays:
            return (), "xrandr --current: no connected output with a current mode"
        return displays, ", ".join(f"{d.name} {_size(d)}" for d in displays)


# ---------------------------------------------------------------------------------------------- declared

_DECLARED = re.compile(r"(\d{3,5})[xX×](\d{3,5})", re.ASCII)


def parse_declared(text: str) -> tuple[Display, ...]:
    """``"3840x2160"`` / ``"3840x2160, 1920×1080"`` → displays named ``declared-1…``.

    Each side 320…16384; duplicates collapse; at most 8. Anything else raises ``DisplaySpecError``.
    """
    sizes: list[tuple[int, int]] = []
    for part in text.split(","):
        spec = part.strip()
        match = _DECLARED.fullmatch(spec)
        if match is None:
            raise DisplaySpecError(_one_line(spec, 40), "expected WIDTHxHEIGHT, e.g. 1920x1080")
        width, height = int(match.group(1)), int(match.group(2))
        if not (DECLARED_MIN <= width <= DECLARED_MAX and DECLARED_MIN <= height <= DECLARED_MAX):
            raise DisplaySpecError(spec, f"each side must be {DECLARED_MIN}…{DECLARED_MAX} pixels")
        if (width, height) not in sizes:
            sizes.append((width, height))
    if len(sizes) > DECLARED_LIMIT:
        raise DisplaySpecError(_one_line(text, 40), f"at most {DECLARED_LIMIT} declared displays")
    return tuple(
        Display(f"declared-{index}", width, height, source=DisplaySource.DECLARED)
        for index, (width, height) in enumerate(sizes, start=1)
    )


# ------------------------------------------------------------------------------------------------- chain


def merge_gdk_drm(
    gdk: Sequence[Display], drm: Sequence[Display]
) -> tuple[tuple[Display, ...], tuple[str, ...]]:
    """Ruling Q5: same connector, GDK and DRM disagree → DRM's pixel size in GDK's orientation.

    Returns the GDK displays (name, scale, primary and source kept) with corrected sizes, and one note per
    correction. Connectors are matched by exact name; a GDK display DRM does not name is left alone, and a
    DRM connector GDK does not show is not added (GDK is the authority on what the session displays).
    """
    by_name = {display.name: display for display in reversed(drm)}
    merged: list[Display] = []
    notes: list[str] = []
    for display in gdk:
        other = by_name.get(display.name)
        if other is not None:
            width, height = other.width, other.height
            if (display.height > display.width) != (height > width) and display.width != display.height:
                width, height = height, width
            if (width, height) != (display.width, display.height):
                notes.append(f"{display.name}: gdk {_size(display)} -> drm {width}x{height}")
                display = replace(display, width=width, height=height)
        merged.append(display)
    return tuple(merged), tuple(notes)


def _run_probe(probe: DisplayProbe) -> tuple[tuple[Display, ...], ProbeAttempt]:
    try:
        displays = tuple(probe.probe())
        detail = str(getattr(probe, "last_detail", "") or "")
    except Exception as exc:
        displays, detail = (), f"{type(exc).__name__}: {exc}"
    if not detail:
        detail = ", ".join(f"{d.name} {_size(d)}" for d in displays) or "no display found"
    return displays, ProbeAttempt(probe.source, bool(displays), _one_line(detail))


def _unique_names(displays: Sequence[Display]) -> list[Display]:
    """The first display of each name, in order (a probe may name one connector twice)."""
    unique: dict[str, Display] = {}
    for display in displays:
        unique.setdefault(display.name, display)
    return list(unique.values())


def detect(probes: Sequence[DisplayProbe], declared: Sequence[Display] = ()) -> DisplayDetection:
    """Run the chain: the first probe returning displays wins; a raising probe is a failed attempt.

    When the winner is the GDK probe and a DRM probe follows it in the chain, that DRM probe is run too and
    sizes are reconciled per ``merge_gdk_drm`` (both attempts are recorded). Declared displays are always
    appended, except one equal in size to a display already in the set. Exactly one display is ``primary``:
    the first flagged, else the first. Never raises; ``reason`` is set exactly when no display was found.
    """
    attempts: list[ProbeAttempt] = []
    detected: list[Display] = []
    for index, probe in enumerate(probes):
        displays, attempt = _run_probe(probe)
        attempts.append(attempt)
        if not displays:
            continue
        detected = _unique_names(displays)
        if probe.source is DisplaySource.GDK:
            drm = next((p for p in probes[index + 1 :] if p.source is DisplaySource.DRM), None)
            if drm is not None:
                drm_displays, drm_attempt = _run_probe(drm)
                merged, notes = merge_gdk_drm(detected, drm_displays)
                detected = list(merged)
                if notes:
                    drm_attempt = replace(
                        drm_attempt, detail=_one_line("; ".join([drm_attempt.detail, *notes]))
                    )
                attempts.append(drm_attempt)
        break

    targets = list(detected)
    kept = 0
    for display in declared:
        if any((t.width, t.height) == (display.width, display.height) for t in targets):
            continue
        if any(t.name == display.name for t in targets):
            continue
        targets.append(display)
        kept += 1
    if declared:
        attempts.append(
            ProbeAttempt(DisplaySource.DECLARED, True, f"{len(declared)} declared, {kept} added as targets")
        )

    if targets:
        primary = next((t for t in targets if t.primary), targets[0])
        targets = [replace(t, primary=t is primary) if t.primary != (t is primary) else t for t in targets]

    reason: Reason | None = None
    if not targets:
        evidence = tuple((attempt.source.value, attempt.detail) for attempt in attempts)
        reason = Reason(
            ReasonCode.DISPLAY_NOT_DETECTED,
            evidence=evidence or (("probes", "none configured"),),
            remedy=REMEDY,
        )
    return DisplayDetection(tuple(targets), tuple(attempts), reason)


def has_session(env: Mapping[str, str]) -> bool:
    """True inside a graphical session: ``DISPLAY`` or ``WAYLAND_DISPLAY`` is set and non-empty."""
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def service_probes(root: Path, env: Mapping[str, str], run: Runner = default_runner) -> list[DisplayProbe]:
    """The service-side chain (ruling Q4): ``[xrandr, DRM]`` inside a session, ``[DRM]`` without one.

    The GUI prepends its ``GdkDisplayProbe``: ``detect([GdkDisplayProbe(), *service_probes(root, env)])``.
    """
    drm = DrmDisplayProbe(root)
    if has_session(env):
        return [XrandrProbe(env, run), drm]
    return [drm]
