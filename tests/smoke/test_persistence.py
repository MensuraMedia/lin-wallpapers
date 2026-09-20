"""Window size and last route survive both ways out: closing the window, and Ctrl+Q (``app.quit``)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import PROJECT_ROOT

pytestmark = pytest.mark.smoke

LINE = r"{} route=(\w+) size=(\d+)x(\d+)"


def _run(config_home: Path, *args: str) -> dict[str, tuple[str, int, int]]:
    # keyfile backend + a temporary XDG_CONFIG_HOME: the user's real dconf is never touched.
    env = {
        **os.environ,
        "GSETTINGS_BACKEND": "keyfile",
        "XDG_CONFIG_HOME": str(config_home),
        "G_DEBUG": "fatal-criticals",
        "NO_AT_BRIDGE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-m", "tests.smoke.drive_persist", *args],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    found = {}
    for key in ("restored", "leaving"):
        match = re.search(LINE.format(key), result.stdout)
        assert match, result.stdout
        found[key] = (match.group(1), int(match.group(2)), int(match.group(3)))
    return found


@pytest.mark.parametrize("door", ["close", "quit"])
def test_state_is_saved_on_the_way_out(tmp_path: Path, door: str) -> None:
    first = _run(tmp_path, door, "history", "1100", "700")
    # Fresh config + empty catalogue: first run lands on the Sources scan hero (M1 acceptance #4).
    assert first["restored"][0] == "sources"
    assert first["leaving"][0] == "history"

    second = _run(tmp_path, "quit" if door == "close" else "close", "sources", "1000", "680")
    assert second["restored"] == first["leaving"], f"{door}: route/size were not saved"
    assert second["restored"][1] >= 960  # never the 0x0 / 1x1 of a destroyed window
    assert second["restored"][2] >= 640

    third = _run(tmp_path, door)
    assert third["restored"] == second["leaving"]

    keyfile = tmp_path / "glib-2.0" / "settings" / "keyfile"
    assert "last-route='sources'" in keyfile.read_text()
