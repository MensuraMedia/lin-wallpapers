"""``config_paths``: XDG overrides are honoured, and every location stays under the (temporary) home."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import config_paths

XDG_VARIABLES = ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")
LOCATIONS = (
    config_paths.data_dir,
    config_paths.cache_dir,
    config_paths.state_dir,
    config_paths.catalogue_db,
    config_paths.thumbs_dir,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary ``$HOME`` with no XDG overrides; the real home is never consulted."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    for variable in XDG_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    return fake


def test_defaults_follow_the_xdg_fallbacks(home: Path) -> None:
    assert config_paths.data_dir() == home / ".local/share/lin-wallpapers"
    assert config_paths.cache_dir() == home / ".cache/lin-wallpapers"
    assert config_paths.state_dir() == home / ".local/state/lin-wallpapers"
    assert config_paths.catalogue_db() == home / ".local/share/lin-wallpapers/catalogue.db"
    assert config_paths.thumbs_dir() == home / ".cache/lin-wallpapers/thumbnails"


def test_xdg_overrides_are_honoured(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "xdg/data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "xdg/cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "xdg/state"))
    assert config_paths.data_dir() == home / "xdg/data/lin-wallpapers"
    assert config_paths.catalogue_db() == home / "xdg/data/lin-wallpapers/catalogue.db"
    assert config_paths.cache_dir() == home / "xdg/cache/lin-wallpapers"
    assert config_paths.thumbs_dir() == home / "xdg/cache/lin-wallpapers/thumbnails"
    assert config_paths.state_dir() == home / "xdg/state/lin-wallpapers"


def test_each_override_moves_only_its_own_locations(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "elsewhere"))
    assert config_paths.thumbs_dir() == home / "elsewhere/lin-wallpapers/thumbnails"
    assert config_paths.catalogue_db() == home / ".local/share/lin-wallpapers/catalogue.db"


@pytest.mark.parametrize("value", ["", "relative/dir", "./here", "~/data"])
def test_empty_or_relative_overrides_are_ignored(
    home: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    for variable in XDG_VARIABLES:
        monkeypatch.setenv(variable, value)
    assert config_paths.data_dir() == home / ".local/share/lin-wallpapers"
    assert config_paths.cache_dir() == home / ".cache/lin-wallpapers"
    assert config_paths.state_dir() == home / ".local/state/lin-wallpapers"


@pytest.mark.parametrize("overridden", [False, True])
def test_every_location_is_absolute_and_under_the_temporary_home(
    home: Path, monkeypatch: pytest.MonkeyPatch, overridden: bool
) -> None:
    if overridden:
        for variable in XDG_VARIABLES:
            monkeypatch.setenv(variable, str(home / "xdg" / variable.lower()))
    for location in LOCATIONS:
        path = location()
        assert path.is_absolute()
        assert path.is_relative_to(home), f"{location.__name__}() escaped the temporary home: {path}"


def test_resolving_a_location_creates_nothing(home: Path) -> None:
    for location in LOCATIONS:
        location()
    assert list(home.iterdir()) == []


def test_the_environment_is_read_at_call_time(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = config_paths.catalogue_db()
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "later"))
    assert config_paths.catalogue_db() == home / "later/lin-wallpapers/catalogue.db"
    assert before != config_paths.catalogue_db()


def test_project_constants_still_point_into_the_checkout() -> None:
    assert (config_paths.PROJECT_ROOT / "pyproject.toml").is_file()
    assert config_paths.CSS_DIR == config_paths.RESOURCES_DIR / "css"
    assert config_paths.GRESOURCE_FILE.parent == config_paths.BUILD_DIR
    assert config_paths.SCHEMA_DIR.parent == config_paths.BUILD_DIR
