"""M1 acceptance #2, in the running app: a real scan of a generated root fills the Browse grid, a
filter narrows it, no GTK critical is emitted, and no worker thread survives the window closing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import PROJECT_ROOT
from tests.helpers import imagegen
from tests.smoke.conftest import require_display

pytestmark = pytest.mark.smoke

NOISE = ("Gtk-WARNING", "Gtk-CRITICAL", "GLib-GObject-CRITICAL", "GLib-CRITICAL", "Gdk-CRITICAL", "Traceback")

LANDSCAPE = 6
PORTRAIT = 4


def _library(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(LANDSCAPE):
        imagegen.make_jpeg(root, f"wide_{index}.jpg", size=(1600, 1000), seed=index + 1)
    for index in range(PORTRAIT):
        imagegen.make_jpeg(root, f"tall_{index}.jpg", size=(1000, 1600), seed=100 + index)


def _env(tmp_path: Path, scan_root: Path) -> dict[str, str]:
    return {
        **os.environ,
        "G_DEBUG": "fatal-criticals",
        "NO_AT_BRIDGE": "1",
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "LWP_SCAN_ROOT": str(scan_root),
    }


def _drive(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tests.smoke.drive_scan", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_scan_fills_the_browse_grid_and_a_filter_narrows_it(tmp_path: Path) -> None:
    require_display()
    scan_root = tmp_path / "library"
    _library(scan_root)
    screenshot = tmp_path / "browse.png"

    result = _drive(_env(tmp_path, scan_root), str(screenshot), "browse")
    assert result.returncode == 0, result.stderr
    for marker in NOISE:
        assert marker not in result.stderr, result.stderr

    line = next(line for line in result.stdout.splitlines() if line.startswith("SCAN "))
    facts = json.loads(line.removeprefix("SCAN "))
    assert facts["scan_result"] == "ok", facts
    assert facts["all_total"] == LANDSCAPE + PORTRAIT, facts
    assert facts["all_cards"] > 0, facts
    # The orientation filter is a real narrowing: only the landscape images survive it.
    assert facts["filtered_total"] == LANDSCAPE, facts
    assert facts["filtered_total"] < facts["all_total"], facts
    assert screenshot.exists() and screenshot.stat().st_size > 0


def test_scan_leaves_no_thread_running(tmp_path: Path) -> None:
    require_display()
    scan_root = tmp_path / "library"
    _library(scan_root)
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.smoke.drive_scan"],
        cwd=PROJECT_ROOT, env=_env(tmp_path, scan_root), start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    assert app.wait(timeout=120) == 0
    survivors = subprocess.run(["pgrep", "-s", str(app.pid)], capture_output=True, text=True, check=False)
    assert survivors.stdout.strip() == ""
