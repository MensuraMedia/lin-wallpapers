"""Pure-part unit tests: no display required."""

from __future__ import annotations

import pytest
from PIL import Image

from linwallpaper import imaging
from linwallpaper.backends import all_backends, detect_backend
from linwallpaper.backends._gsettings import path_to_uri, uri_to_path
from linwallpaper.backends.cinnamon import CinnamonBackend
from linwallpaper.monitors import MonitorInfo


@pytest.fixture()
def sample(tmp_path):
    p = tmp_path / "sample.png"
    Image.new("RGB", (400, 300), (120, 60, 30)).save(p)
    return str(p)


@pytest.mark.parametrize("fit", imaging.FITS)
@pytest.mark.parametrize("size", [(800, 600), (1920, 1080), (256, 256)])
def test_transform_output_size(sample, fit, size):
    out = imaging.transform(sample, size, fit)
    assert out.size == size


def test_transform_rejects_bad_fit(sample):
    with pytest.raises(ValueError):
        imaging.transform(sample, (100, 100), "nope")


def test_supported_formats_nonempty():
    fmts = imaging.supported_formats()
    assert len(fmts) > 0
    assert imaging.supported_mime_types()  # non-empty flat list
    assert any("png" in f["name"] for f in fmts)


def test_detect_picks_cinnamon_here():
    be = detect_backend()
    assert be is not None
    assert be.name == "Cinnamon"


def test_all_backends_registered():
    names = {b.name for b in all_backends()}
    assert {"Cinnamon", "GNOME", "MATE", "Xfce"}.issubset(names)


def test_fit_to_picture_options_mapping():
    be = CinnamonBackend()
    assert be.option_map[imaging.FIT_FILL] == "zoom"
    assert be.option_map[imaging.FIT_FIT] == "scaled"
    assert be.option_map[imaging.FIT_CENTER] == "centered"
    assert be.option_map[imaging.FIT_STRETCH] == "stretched"


def test_uri_roundtrip():
    p = "/home/user/Pictures/a b.png"
    assert uri_to_path(path_to_uri(p)) == p


def test_validate_accepts_real_image(sample):
    ok, reason = imaging.validate(sample)
    assert ok
    assert reason == "ok"


def test_validate_rejects_missing_file(tmp_path):
    ok, reason = imaging.validate(tmp_path / "does-not-exist.png")
    assert not ok
    assert "not found" in reason


def test_validate_rejects_non_image(tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("this is definitely not an image")
    ok, reason = imaging.validate(junk)
    assert not ok
    assert reason  # a human-readable reason, no exception


def test_validate_rejects_directory(tmp_path):
    ok, _reason = imaging.validate(tmp_path)
    assert not ok


def test_validate_rejects_truncated_image(tmp_path, sample):
    # Copy only the first few bytes: a real header, but corrupt body.
    truncated = tmp_path / "broken.png"
    from pathlib import Path

    truncated.write_bytes(Path(sample).read_bytes()[:64])
    ok, _reason = imaging.validate(truncated)
    assert not ok


def _mon(name, w, h, x, scale=1, primary=False):
    return MonitorInfo(name=name, width=w, height=h, scale=scale, x=x, y=0, primary=primary)


def test_cinnamon_apply_one_screen_builds_spanned_composite(sample):
    monitors = [_mon("DP-1", 1920, 1080, 0, primary=True), _mon("HDMI-1", 1920, 1080, 1920)]
    calls: list[list[str]] = []

    def fake_run(argv):
        calls.append(argv)
        if argv[:2] == ["gsettings", "get"]:
            return "" if argv[3] == "picture-uri" else "zoom"
        if argv[:2] == ["gsettings", "list-schemas"]:
            return "org.cinnamon.desktop.background"
        return ""

    be = CinnamonBackend(runner=fake_run)
    result = be.apply(sample, imaging.FIT_FILL, monitors=monitors, target="HDMI-1")

    sets = [c for c in calls if c[:2] == ["gsettings", "set"]]
    opt = next(c[4] for c in sets if c[3] == "picture-options")
    uri = next(c[4] for c in sets if c[3] == "picture-uri")
    assert opt == "spanned"
    composite = uri_to_path(uri)
    assert composite.endswith(".png")
    # the composite must actually exist and span both monitors (3840x1080)
    img = imaging.load(composite)
    assert img.size == (3840, 1080)
    assert result.target == "HDMI-1"
    assert "composite" in result.note


def test_cinnamon_apply_all_uses_injected_runner(sample):
    calls: list[list[str]] = []
    reads = {
        ("picture-uri",): "file:///old.png",
        ("picture-options",): "stretched",
    }

    def fake_run(argv):
        calls.append(argv)
        if argv[:2] == ["gsettings", "get"]:
            return reads.get((argv[3],), "")
        if argv[:2] == ["gsettings", "list-schemas"]:
            return "org.cinnamon.desktop.background"
        return ""

    be = CinnamonBackend(runner=fake_run)
    result = be.apply(sample, imaging.FIT_FILL, monitors=[], target="all")
    sets = [c for c in calls if c[:2] == ["gsettings", "set"]]
    assert any(c[3] == "picture-uri" and c[4].startswith("file://") for c in sets)
    assert any(c[3] == "picture-options" and c[4] == "zoom" for c in sets)
    assert result.previous["picture-uri"] == "file:///old.png"


# ---- per-surface image overrides (gi-free AppState) ----------------------
def _state():
    from linwallpaper.ui.state import AppState

    monitors = [MonitorInfo("DP-1", 1920, 1080, 1, 0, 0, True)]
    return AppState(backend=None, monitors=monitors, desktop="Test")


def test_resolved_image_is_override_or_global():
    st = _state()
    # No image anywhere -> None.
    assert st.resolved_image("DP-1") is None
    # Global only -> every surface resolves to the global image.
    st.set_image("/img/global.png")
    assert st.resolved_image("DP-1") == "/img/global.png"
    assert st.resolved_image("login") == "/img/global.png"
    # An override wins for its own surface, others still follow the global.
    st.set_surface_image("login", "/img/login.png")
    assert st.resolved_image("login") == "/img/login.png"
    assert st.resolved_image("DP-1") == "/img/global.png"


def test_set_surface_image_touches_only_that_surface():
    st = _state()
    st.set_image("/img/global.png")
    st.set_surface_image("splash", "/img/splash.png")
    # Only "splash" has an override; the global image is unchanged.
    assert st.surface_image == {"splash": "/img/splash.png"}
    assert st.image_path == "/img/global.png"
    # Clearing overrides makes every surface follow the global again.
    st.clear_surface_images()
    assert st.surface_image == {}
    assert st.resolved_image("splash") == "/img/global.png"
