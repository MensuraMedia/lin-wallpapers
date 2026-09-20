"""Shell constants pinned to the design language, and the bundle-freshness decision (no GTK needed)."""

from __future__ import annotations

import os
from pathlib import Path

from src.config.config_layout import Layout
from src.config.config_paths import CSS_DIR
from src.config.config_theme import BUNDLE_MANIFEST, STYLE_FILE, bundle_is_fresh, bundle_sources


def _touch(path: Path, when: int) -> Path:
    path.write_text("x")
    os.utime(path, ns=(when, when))
    return path


def test_shell_dimensions_match_the_design_language() -> None:
    """The smoke test checks the rendered shell against these constants; this pins the constants."""
    dims = Layout.dimensions
    assert dims.SIDEBAR_WIDTH == 150  # the starter template's width (CLAUDE.md)
    assert dims.NAV_BUTTON_HEIGHT == 28
    assert dims.NAV_ICON_SIZE == 14
    assert f"min-height: {dims.NAV_BUTTON_HEIGHT}px" in STYLE_FILE.read_text()


def test_missing_bundle_is_not_fresh(tmp_path: Path) -> None:
    source = _touch(tmp_path / "style.css", 1_000)
    assert not bundle_is_fresh(tmp_path / "absent.gresource", [source])


def test_bundle_newer_than_every_source_is_fresh(tmp_path: Path) -> None:
    sources = [_touch(tmp_path / "tokens.css", 1_000), _touch(tmp_path / "style.css", 2_000)]
    bundle = _touch(tmp_path / "app.gresource", 3_000)
    assert bundle_is_fresh(bundle, sources)
    assert bundle_is_fresh(_touch(bundle, 2_000), sources)  # same instant: not older


def test_one_newer_source_makes_the_bundle_stale(tmp_path: Path) -> None:
    sources = [_touch(tmp_path / "tokens.css", 1_000), _touch(tmp_path / "style.css", 5_000)]
    bundle = _touch(tmp_path / "app.gresource", 3_000)
    assert not bundle_is_fresh(bundle, sources)
    manifest = _touch(tmp_path / "app.gresource.xml", 9_000)
    assert not bundle_is_fresh(bundle, [sources[0], manifest])


def test_absent_sources_are_ignored(tmp_path: Path) -> None:
    """An installed package ships the bundle without ``resources/``."""
    bundle = _touch(tmp_path / "app.gresource", 3_000)
    assert bundle_is_fresh(bundle, [tmp_path / "gone.css"])
    assert bundle_is_fresh(bundle, [])


def test_bundle_sources_cover_every_stylesheet_and_the_manifest() -> None:
    sources = bundle_sources()
    assert BUNDLE_MANIFEST in sources
    assert BUNDLE_MANIFEST.exists()
    assert set(CSS_DIR.glob("*.css")) <= set(sources)
    manifest = BUNDLE_MANIFEST.read_text()
    for sheet in CSS_DIR.glob("*.css"):
        assert f"css/{sheet.name}" in manifest, f"{sheet.name} is not in the bundle"
