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


def _apply_buttons(widget):
    return [
        w
        for w in _walk(widget)
        if isinstance(w, Gtk.Button) and w.get_label() == "Apply"
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


def test_monitor_frame_is_large_and_uncapped():
    from linwallpaper.ui.monitor_frame import _MAX_WIDTH, MonitorFrame

    # The bezel target width is large and the old min(..., 320) cap is gone, so
    # the screen area takes the full target width at the requested ratio.
    assert _MAX_WIDTH >= 460
    frame = MonitorFrame(ratio=16 / 9)
    overlay = next(w for w in _walk(frame) if isinstance(w, Gtk.Overlay))
    width, _height = overlay.get_size_request()
    assert width == _MAX_WIDTH


def test_screens_monitors_share_one_aspect(tmp_path):
    from linwallpaper.ui.monitor_frame import MonitorFrame

    sample = tmp_path / "s.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(sample)
    # A wide primary + a 16:9 secondary: every sim monitor must still use the
    # primary's aspect so all cards render at the same shape and size.
    monitors = [
        MonitorInfo("DP-1", 2560, 1080, 1, 0, 0, True),
        MonitorInfo("HDMI-1", 1920, 1080, 1, 2560, 0, False),
    ]
    page = _make_page(monitors, _FakeBackend(), image_path=str(sample))

    primary_aspect = 2560 / 1080
    # The recorded preview ratio for every surface is the primary aspect.
    assert {round(r, 6) for (_f, r, _g) in page._previews.values()} == {
        round(primary_aspect, 6)
    }
    # And every actual MonitorFrame widget carries that same ratio.
    frames = [w for w in _walk(page) if isinstance(w, MonitorFrame)]
    assert frames
    assert all(f.ratio == pytest.approx(primary_aspect) for f in frames)


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
    def __init__(self):
        self.applies: list[tuple] = []  # (target, image, fit)
        self.toasts: list[str] = []

    def apply(self, target, image=None, fit=None):
        self.applies.append((target, image, fit))

    def toast(self, message):
        self.toasts.append(message)

    def open_image_dialog(self, on_chosen=None):  # pragma: no cover - not driven here
        pass


def _make_page(monitors, backend, image_path=None, win=None):
    from linwallpaper.ui.pages.screens import ScreensPage
    from linwallpaper.ui.state import AppState

    state = AppState(backend=backend, monitors=monitors, desktop="Test")
    if image_path:
        state.image_path = image_path
    return ScreensPage(state, win or _StubWin())


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


def test_screens_every_card_has_apply(tmp_path):
    sample = tmp_path / "s.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(sample)
    monitors = [MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True)]
    page = _make_page(monitors, _FakeBackend(), image_path=str(sample))

    # desktop + lock + 3 privileged = 5 Apply buttons; all enabled (image set).
    buttons = _apply_buttons(page)
    assert len(buttons) == 5
    assert all(b.get_sensitive() for b in buttons)

    # The 3 root surfaces carry a "requires password" caption; desktop/lock do not.
    captions = [
        w
        for w in _walk(page)
        if isinstance(w, Gtk.Label) and w.get_text() == "requires password"
    ]
    assert len(captions) == 3


def test_screens_apply_disabled_without_image():
    monitors = [MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True)]
    page = _make_page(monitors, _FakeBackend(), image_path=None)
    # No image chosen: every Apply is disabled (nothing to render/apply).
    buttons = _apply_buttons(page)
    assert buttons
    assert all(not b.get_sensitive() for b in buttons)


def test_screens_fit_control_updates_surface_state(tmp_path):
    sample = tmp_path / "s.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(sample)
    monitors = [MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True)]
    page = _make_page(monitors, _FakeBackend(), image_path=str(sample))

    # Each surface tracks its own fit; toggling "Center" on the login card sets it.
    center = [
        w
        for w in _walk(page)
        if isinstance(w, Gtk.ToggleButton) and w.get_label() == "Center"
    ]
    assert center  # one per card
    center[0].set_active(True)
    assert "center" in page._fits.values()


def test_screens_global_fit_propagates_to_all_surfaces(tmp_path):
    sample = tmp_path / "s.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(sample)
    monitors = [
        MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True),
        MonitorInfo("HDMI-1", 1920, 1080, 1, 1920, 0, False),
    ]
    page = _make_page(monitors, _FakeBackend(), image_path=str(sample))

    # The global FIT control sets the fit for EVERY surface at once.
    page._global_fit_btns["center"].set_active(True)
    assert page.state.fit == "center"
    # Two desktops + lock + three privileged = six surfaces, all now "center".
    assert len(page._fits) == 6
    assert set(page._fits.values()) == {"center"}


def test_screens_per_surface_open_sets_only_that_surface(tmp_path):
    sample = tmp_path / "global.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(sample)
    login_img = tmp_path / "login.png"
    Image.new("RGB", (640, 480), (90, 30, 60)).save(login_img)
    monitors = [MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True)]
    page = _make_page(monitors, _FakeBackend(), image_path=str(sample))

    # Opening an image on the login card overrides ONLY that surface.
    page._set_surface_image("login", str(login_img))
    assert page.state.surface_image == {"login": str(login_img)}
    # Resolved image = override for login, global for everything else.
    assert page.state.resolved_image("login") == str(login_img)
    assert page.state.resolved_image("DP-1") == str(sample)


def test_screens_apply_to_all_targets_desktop_and_lock_only(tmp_path):
    sample = tmp_path / "s.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(sample)
    monitors = [
        MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True),
        MonitorInfo("HDMI-1", 1920, 1080, 1, 1920, 0, False),
    ]
    win = _StubWin()
    page = _make_page(monitors, _FakeBackend(), image_path=str(sample), win=win)

    page._on_apply_all()

    targets = [t for (t, _img, _fit) in win.applies]
    # Every desktop monitor connector + the lock surface ("all"); nothing else.
    assert targets == ["DP-1", "HDMI-1", "all"]
    # The privileged (root) surfaces are never applied here.
    assert not ({"login", "splash", "grub"} & set(targets))
    # Every apply carried the global image.
    assert all(img == str(sample) for (_t, img, _f) in win.applies)
    # The toast steers the user to per-card Apply for the password surfaces.
    assert any("login/boot" in m for m in win.toasts)


def test_screens_apply_to_all_needs_an_image():
    monitors = [MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True)]
    win = _StubWin()
    page = _make_page(monitors, _FakeBackend(), image_path=None, win=win)

    page._on_apply_all()
    # Nothing applied; the user is told to choose an image first.
    assert win.applies == []
    assert any("Choose an image" in m for m in win.toasts)


def test_password_dialog_builds():
    from linwallpaper.ui.password_dialog import PasswordDialog, detect_auth_method

    method = detect_auth_method()
    assert method in ("sudo", "pkexec")
    captured = {}
    dlg = PasswordDialog(
        None, surface="login", method="sudo", on_submit=lambda pw: captured.setdefault("pw", pw)
    )
    # The masked entry must be a PasswordEntry (never a plain Entry).
    entries = [w for w in _walk(dlg) if isinstance(w, Gtk.PasswordEntry)]
    assert len(entries) == 1
    # Cancel + Apply buttons present.
    labels = {w.get_label() for w in _walk(dlg) if isinstance(w, Gtk.Button)}
    assert {"Cancel", "Apply"}.issubset(labels)
