"""Unit tests for the wallpaper library, settings store, add-CLI and providers.

All isolated to a temp ``$XDG_DATA_HOME`` / ``$XDG_CONFIG_HOME`` — nothing here
touches the real ``~/.local/share`` or a real file manager.
"""

from __future__ import annotations

import pytest
from PIL import Image

from linwallpaper import addcli
from linwallpaper.collection import Collection
from linwallpaper.config import Settings
from linwallpaper.contextmenu import default_exec_cmd, detect_context_provider
from linwallpaper.contextmenu.nemo import NemoProvider


@pytest.fixture()
def images(tmp_path):
    d = tmp_path / "pics"
    d.mkdir()
    paths = []
    for i in range(3):
        p = d / f"img{i}.png"
        Image.new("RGB", (64, 40), (i * 40, 60, 90)).save(p)
        paths.append(str(p))
    (d / "notes.txt").write_text("not an image")  # decoy
    return d, paths


@pytest.fixture()
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))


# ---- Collection ----------------------------------------------------------
def test_builtin_default_is_present_first_and_locked(isolate):
    c = Collection()
    items = c.items()
    assert items[0].builtin is True
    assert items[0].removable is False
    assert c.remove(items[0].path) is False  # cannot remove the built-in


def test_add_files_dedupes_and_skips_non_images(isolate, images):
    _d, paths = images
    c = Collection()
    res = c.add_paths(paths)
    assert res.added == 3
    again = c.add_paths(paths)  # same files → all skipped
    assert again.added == 0 and again.skipped == 3
    # built-in + 3 files
    assert len(c.items()) == 4


def test_add_folder_scans_supported_images_only(isolate, images):
    d, _paths = images
    c = Collection()
    res = c.add_paths([str(d)])
    assert res.dirs_scanned == 1
    assert res.added == 3  # the .txt decoy is skipped


def test_remove_and_missing_file(isolate, images, tmp_path):
    _d, paths = images
    c = Collection()
    c.add_paths(paths)
    assert c.remove(paths[0]) is True
    assert len(c.items()) == 3  # built-in + 2

    # a referenced file that disappears is reported as not-exists, not dropped
    gone = tmp_path / "pics" / "img1.png"
    gone.unlink()
    fresh = Collection()  # reload from disk
    missing = [i for i in fresh.items() if i.path == str(gone.resolve())]
    assert missing and missing[0].exists is False


def test_collection_persists_across_instances(isolate, images):
    _d, paths = images
    Collection().add_paths(paths)
    assert len(Collection().items()) == 4  # reloaded from collection.json


def test_reload_picks_up_external_writes(isolate, images):
    _d, paths = images
    view = Collection()
    assert len(view.items()) == 1  # just the built-in
    # a separate process (the add-CLI) writes to the same index
    Collection().add_paths(paths)
    assert len(view.items()) == 1  # still stale in memory
    view.reload()
    assert len(view.items()) == 4  # now sees the external additions


# ---- Settings ------------------------------------------------------------
def test_settings_roundtrip(isolate):
    s = Settings()
    assert s.get("context_menu", False) is False
    s.set("context_menu", True)
    assert Settings().get("context_menu") is True  # persisted


# ---- add-CLI -------------------------------------------------------------
def test_addcli_requires_args(isolate, capsys):
    assert addcli.main([]) == 2


def test_addcli_adds_to_library(isolate, images):
    _d, paths = images
    assert addcli.main(paths) == 0
    assert len(Collection().items()) == 4


# ---- context-menu providers ---------------------------------------------
def test_default_exec_cmd_targets_addcli():
    cmd = default_exec_cmd()
    assert "linwallpaper.addcli" in cmd
    assert "PYTHONPATH" in cmd


def test_nemo_install_uninstall(isolate):
    p = NemoProvider()
    assert p.is_installed() is False
    p.install()
    assert p.is_installed() is True
    text = p._file.read_text()
    assert "[Nemo Action]" in text
    assert "linwallpaper.addcli" in text
    assert "dir;" in text  # folders eligible too
    p.uninstall()
    assert p.is_installed() is False


def test_detect_returns_a_provider_when_a_fm_is_present():
    # On any machine with a supported FM on PATH this is non-None; if none is
    # installed it is None. Either way the call must not raise.
    prov = detect_context_provider()
    assert prov is None or hasattr(prov, "install")
