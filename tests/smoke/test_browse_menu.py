"""In the running app: a REAL right-click on a Browse *grid* card opens the context-menu popover.

The card sits inside ``Gtk.FlowBox``/``FlowBoxChild``; the menu is opened by dispatching a genuine
button-3 ``Gdk`` event through ``Gtk.main_do_event`` (the real toplevel input path), never by calling
the handler. This proves the ``compat.click_target`` fix makes the live Browse right-click work. No GTK
critical is emitted (``G_DEBUG=fatal-criticals``) and no thread survives the window closing.
"""

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
        [sys.executable, "-m", "tests.smoke.drive_browse_menu", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_real_right_click_opens_the_browse_grid_menu(tmp_path: Path) -> None:
    require_display()
    scan_root = tmp_path / "library"
    _library(scan_root)
    screenshot = tmp_path / "browse-menu.png"

    result = _drive(_env(tmp_path, scan_root), str(screenshot))
    assert result.returncode == 0, result.stderr
    for marker in NOISE:
        assert marker not in result.stderr, result.stderr

    line = next(line for line in result.stdout.splitlines() if line.startswith("BMENU "))
    facts = json.loads(line.removeprefix("BMENU "))
    assert facts["have_card"] is True, facts
    assert facts["menu_visible"] is True, facts  # a real button-3 event opened the popover
    assert facts["menu_via"] == "main_do_event", facts  # inside the FlowBox, via the real input path
    assert screenshot.exists() and screenshot.stat().st_size > 0


def test_browse_menu_leaves_no_thread_running(tmp_path: Path) -> None:
    require_display()
    scan_root = tmp_path / "library"
    _library(scan_root)
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.smoke.drive_browse_menu"],
        cwd=PROJECT_ROOT, env=_env(tmp_path, scan_root), start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    assert app.wait(timeout=120) == 0
    survivors = subprocess.run(["pgrep", "-s", str(app.pid)], capture_output=True, text=True, check=False)
    assert survivors.stdout.strip() == ""
