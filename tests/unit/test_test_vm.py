"""``TestVM`` — the Test page's one-image source: catalogue first, then a fallback picture directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.viewmodels.test_vm import TestImage, TestVM
from tests.helpers import imagegen
from tests.unit.test_services import add_library, make_services, run_scan, wait


def test_disk_fallback_returns_first_readable_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        pics = tmp_path / "pics"
        pics.mkdir()
        imagegen.make_jpeg(pics, "a.jpg", size=(640, 480), seed=1)
        out: list[TestImage | None] = []
        wait(TestVM(services, [pics]).load(out.append))

        assert len(out) == 1
        image = out[0]
        assert isinstance(image, TestImage)
        assert image.name == "a.jpg"
        assert (image.width, image.height) == (640, 480)
        assert image.data is not None and len(image.data) > 0
    finally:
        services.close()


def test_catalogue_is_preferred_over_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        add_library(services, tmp_path / "lib", [("wide.jpg", (1600, 1000))])
        run_scan(services)
        out: list[TestImage | None] = []
        wait(TestVM(services, []).load(out.append))  # no disk dirs: only the catalogue can answer

        image = out[0]
        assert isinstance(image, TestImage)
        assert image.name == "wide.jpg"
        assert (image.width, image.height) == (1600, 1000)
        assert image.data is not None  # the cached thumbnail bytes
    finally:
        services.close()


def test_none_when_nothing_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        out: list[TestImage | None] = []
        wait(TestVM(services, [tmp_path / "does-not-exist"]).load(out.append))
        assert out == [None]
    finally:
        services.close()
