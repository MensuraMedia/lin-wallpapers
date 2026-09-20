"""P6-I — ``GdkDisplayProbe`` (needs a real GDK display, hence the ``smoke`` marker)."""

from __future__ import annotations

import pytest

from src.scanner.displays import Display, DisplaySource


@pytest.mark.smoke
def test_gdk_probe_returns_displays_or_empty() -> None:
    from src.viewmodels.gdk_displays import GdkDisplayProbe

    probe = GdkDisplayProbe()
    assert probe.source == DisplaySource.GDK

    result = probe.probe()  # never raises: detect() would treat an exception as a failed attempt
    assert isinstance(result, tuple)
    assert all(isinstance(display, Display) for display in result)
    assert all(display.width > 0 and display.height > 0 for display in result)
