"""In the running app: a REAL right-click on the Test page's plain card opens the context-menu popover.

This is the clean-room proof the Browse right-click lacked — the card is a plain ``Gtk.Box`` (no
``FlowBox``), and the menu is opened by dispatching a genuine button-3 ``Gdk`` event through the real
event machinery (``drive_test_menu.py``), never by calling the card's handler. No GTK critical is
emitted (``G_DEBUG=fatal-criticals``) and no thread survives the window closing.
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


def _seed(image_dir: Path) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    imagegen.make_jpeg(image_dir, "verify.jpg", size=(1280, 800), seed=7)


def _env(tmp_path: Path, image_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "G_DEBUG": "fatal-criticals",
        "NO_AT_BRIDGE": "1",
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "LWP_TEST_IMAGE_DIR": str(image_dir),
    }


def _drive(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tests.smoke.drive_test_menu", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_real_right_click_opens_the_menu(tmp_path: Path) -> None:
    require_display()
    image_dir = tmp_path / "one-image"
    _seed(image_dir)
    screenshot = tmp_path / "test-page-menu.png"

    result = _drive(_env(tmp_path, image_dir), str(screenshot))
    assert result.returncode == 0, result.stderr
    for marker in NOISE:
        assert marker not in result.stderr, result.stderr

    line = next(line for line in result.stdout.splitlines() if line.startswith("MENU "))
    facts = json.loads(line.removeprefix("MENU "))
    assert facts["have_card"] is True, facts
    assert facts["image_name"] == "verify.jpg", facts
    assert facts["menu_visible"] is True, facts  # a real button-3 event opened the popover
    assert facts["menu_via"] == "main_do_event", facts  # via the real toplevel input path
    assert screenshot.exists() and screenshot.stat().st_size > 0


def test_test_page_leaves_no_thread_running(tmp_path: Path) -> None:
    require_display()
    image_dir = tmp_path / "one-image"
    _seed(image_dir)
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.smoke.drive_test_menu"],
        cwd=PROJECT_ROOT, env=_env(tmp_path, image_dir), start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    assert app.wait(timeout=120) == 0
    survivors = subprocess.run(["pgrep", "-s", str(app.pid)], capture_output=True, text=True, check=False)
    assert survivors.stdout.strip() == ""
