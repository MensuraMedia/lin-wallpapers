"""M1.7, in the running app: right-click *Exclude Image* on a Browse card removes it and creates a FILE
rule, Undo brings it back, no GTK critical is emitted, and no worker thread survives the window closing."""

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

COUNT = 5


def _library(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(COUNT):
        imagegen.make_jpeg(root, f"wide_{index}.jpg", size=(1600, 1000), seed=index + 1)


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
        [sys.executable, "-m", "tests.smoke.drive_exclude", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_exclude_image_removes_the_card_and_undo_restores_it(tmp_path: Path) -> None:
    require_display()
    scan_root = tmp_path / "library"
    _library(scan_root)
    screenshot = tmp_path / "excluded.png"

    result = _drive(_env(tmp_path, scan_root), str(screenshot))
    assert result.returncode == 0, result.stderr
    for marker in NOISE:
        assert marker not in result.stderr, result.stderr

    line = next(line for line in result.stdout.splitlines() if line.startswith("EXCL "))
    facts = json.loads(line.removeprefix("EXCL "))
    assert facts["scan_result"] == "ok", facts
    assert facts["all_total"] == COUNT, facts
    assert facts["exclude_ok"] is True, facts
    assert facts["file_rules"] == 1, facts  # a FILE rule was created
    assert facts["after_exclude_total"] == COUNT - 1, facts  # the card left the grid
    assert facts["after_undo_total"] == COUNT, facts  # undo brought it back
    assert facts["menu_and_toast"] is True, facts  # the real popover + toast path ran cleanly
    assert screenshot.exists() and screenshot.stat().st_size > 0


def test_exclude_leaves_no_thread_running(tmp_path: Path) -> None:
    require_display()
    scan_root = tmp_path / "library"
    _library(scan_root)
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.smoke.drive_exclude"],
        cwd=PROJECT_ROOT, env=_env(tmp_path, scan_root), start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    assert app.wait(timeout=120) == 0
    survivors = subprocess.run(["pgrep", "-s", str(app.pid)], capture_output=True, text=True, check=False)
    assert survivors.stdout.strip() == ""
