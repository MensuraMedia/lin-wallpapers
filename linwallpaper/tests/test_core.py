"""Pure-part unit tests: no display required."""

from __future__ import annotations

import pytest
from PIL import Image

from linwallpaper import imaging
from linwallpaper.backends import all_backends, detect_backend
from linwallpaper.backends._gsettings import path_to_uri, uri_to_path
from linwallpaper.backends.cinnamon import CinnamonBackend


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
