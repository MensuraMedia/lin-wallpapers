"""Smoke tests need a display. Without one they skip — unless ``LWP_SMOKE_REQUIRED=1`` (set by
``make smoke``), where a skipped smoke suite must not read as a green build, so they fail instead."""

from __future__ import annotations

import os

import pytest

NO_DISPLAY = "no display: set DISPLAY/WAYLAND_DISPLAY or install xvfb (sudo apt install xvfb)"


def has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def require_display() -> None:
    """Skip — or fail, when the smoke suite is required — if there is nowhere to open a window."""
    if has_display():
        return
    if os.environ.get("LWP_SMOKE_REQUIRED") == "1":
        pytest.fail(NO_DISPLAY, pytrace=False)
    pytest.skip(NO_DISPLAY)


@pytest.fixture(autouse=True)
def _display_or_skip(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("smoke") is not None:
        require_display()
