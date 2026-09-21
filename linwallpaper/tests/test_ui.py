"""UI tests that need a display: MonitorFrame aspect + Screens surfaces.

Skipped automatically when no display / GTK is available (e.g. headless CI without
xvfb), so the pure test suite still runs everywhere.
"""

from __future__ import annotations

import pytest
from PIL import Image

from linwallpaper.monitors import MonitorInfo

_DISPLAY_OK = False
try:  # pragma: no cover - environment probe
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    Adw.init()
    _DISPLAY_OK = Gdk.Display.get_default() is not None
except Exception:  # pragma: no cover - headless
    _DISPLAY_OK = False

pytestmark = pytest.mark.skipif(not _DISPLAY_OK, reason="no display / GTK unavailable")


def _walk(widget):
    """Yield every descendant widget depth-first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


def _labels(widget) -> list[str]:
    return [w.get_text() for w in _walk(widget) if isinstance(w, Gtk.Label)]


def _set_here_buttons(widget):
    return [
        w
        for w in _walk(widget)
        if isinstance(w, Gtk.Button) and w.get_label() == "Set here"
    ]


def test_monitor_frame_pins_aspect():
    from linwallpaper.ui.monitor_frame import MonitorFrame

    frame = MonitorFrame(ratio=16 / 9)
    assert frame.ratio == pytest.approx(16 / 9)
    aspect = next(w for w in _walk(frame) if isinstance(w, Gtk.AspectFrame))
    # obey_child=False is what stops the picture from ever stretching the card.
    assert aspect.get_obey_child() is False
    assert aspect.get_ratio() == pytest.approx(16 / 9)

    frame.set_ratio(4 / 3)
    assert aspect.get_ratio() == pytest.approx(4 / 3)


def test_monitor_frame_placeholder_and_image(tmp_path):
    from linwallpaper.ui.monitor_frame import MonitorFrame

    frame = MonitorFrame(ratio=16 / 9)
    frame.set_placeholder("nothing here")
    assert "nothing here" in _labels(frame)

    img = Image.new("RGB", (320, 180), (10, 120, 200))
    frame.set_image(img)  # must not raise; accepts a Pillow image


class _FakeBackend:
    name = "Fake"
    supports_per_monitor = False
    uri_key = "picture-uri"
    uri_is_path = False

    def __init__(self, uri=""):
        self._uri = uri

    def current(self):
        return {self.uri_key: self._uri, "picture-options": "zoom"}


class _StubWin:
    def apply(self, target):  # pragma: no cover - not exercised here
        pass


def _make_page(monitors, backend, image_path=None):
    from linwallpaper.ui.pages.screens import ScreensPage
    from linwallpaper.ui.state import AppState

    state = AppState(backend=backend, monitors=monitors, desktop="Test")
    if image_path:
        state.image_path = image_path
    return ScreensPage(state, _StubWin())


def test_screens_lists_all_surfaces(tmp_path):
    sample = tmp_path / "s.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(sample)
    monitors = [
        MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True),
        MonitorInfo("HDMI-1", 1920, 1080, 1, 1920, 0, False),
    ]
    page = _make_page(monitors, _FakeBackend(), image_path=str(sample))

    labels = _labels(page)
    # 2 desktop cards + lock + 3 privileged surfaces.
    assert "Desktop — DP-1" in labels
    assert "Desktop — HDMI-1" in labels
    assert "Lock screen" in labels
    assert "Login screen" in labels
    assert "Boot splash" in labels
    assert "Boot menu" in labels

    n_cards = sum(
        1 for w in _walk(page) if isinstance(w, Gtk.Box) and w.has_css_class("lw-screen-card")
    )
    assert n_cards == 6


def test_screens_desktop_live_privileged_disabled(tmp_path):
    sample = tmp_path / "s.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(sample)
    monitors = [MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True)]
    page = _make_page(monitors, _FakeBackend(), image_path=str(sample))

    buttons = _set_here_buttons(page)
    sensitive = [b.get_sensitive() for b in buttons]
    # Exactly one live "Set here" (the desktop card); the 3 privileged are disabled.
    assert sensitive.count(True) == 1
    assert sensitive.count(False) == 3

    reasons = [
        w.get_text()
        for w in _walk(page)
        if isinstance(w, Gtk.Label) and "privileged apply engine" in w.get_text()
    ]
    assert len(reasons) == 3  # login + boot splash + boot menu
