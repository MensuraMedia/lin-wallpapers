"""P6-I — ``AppServices`` (the gi-free GUI composition root) and shared view-model test helpers.

These helpers build a real catalogue under a tmp ``$XDG`` home, wired to fake probes and the
``immediate_scheduler`` (no display, no GTK), and are imported by the other ``test_*_vm`` modules.
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import cast

import pytest

from src.catalogue.db import set_setting
from src.catalogue.ingest import ScanProgress, ScanSummary
from src.catalogue.thumbs import ThumbCache
from src.scanner.displays import Display
from src.scanner.roots import MountTable
from src.util.cancel import CancelToken
from src.util.threads import Scheduler, immediate_scheduler, run_in_worker
from src.viewmodels.services import AppServices
from tests.helpers import imagegen


class _NullListener:
    def on_progress(self, p: ScanProgress) -> None:
        return None


def wait(handle: object, timeout: float = 10.0) -> object:
    """Block on the ``Future`` a view-model method returns; with ``immediate_scheduler`` the ``on_done``
    callback has already run (updating state) by the time the future resolves."""
    return cast("Future[object]", handle).result(timeout=timeout)


def make_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, scheduler: Scheduler = immediate_scheduler
) -> AppServices:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    services = AppServices(
        tmp_path / "catalogue.db",
        scheduler,
        [],
        mounts=lambda: MountTable(),
        thumbs=ThumbCache(base=tmp_path / "thumbs"),
    )
    services.writer.submit(lambda c: set_setting(c, "scan.min_file_bytes", 0)).result()
    return services


def add_library(services: AppServices, lib: Path, images: list[tuple[str, tuple[int, int]]]) -> int:
    lib.mkdir(parents=True, exist_ok=True)
    for index, (name, size) in enumerate(images):
        imagegen.make_jpeg(lib, name, size=size, seed=index + 1)

    def job(conn: sqlite3.Connection) -> int:
        cursor = conn.execute("INSERT INTO root(path, kind, enabled) VALUES (?, 'user', 1)", (str(lib),))
        return int(cursor.lastrowid or 0)

    return services.writer.submit(job).result()


def run_scan(services: AppServices, declared: tuple[Display, ...] = ()) -> ScanSummary:
    return services.scan.scan(None, list(declared), _NullListener(), CancelToken())


# ── tests ────────────────────────────────────────────────────────────────────────────────────────────────


def test_app_services_builds_and_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    try:
        count = run_in_worker(
            lambda: services.read().execute("SELECT count(*) FROM image").fetchone()[0],
            scheduler=immediate_scheduler,
        ).result()
        assert count == 0
    finally:
        services.close()


def test_close_leaves_no_thread_alive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    services.writer.submit(lambda c: None).result()
    run_in_worker(lambda: 1, scheduler=immediate_scheduler).result()

    services.close()

    alive = [t.name for t in threading.enumerate() if t.is_alive()]
    assert not any(name.startswith("lwp-writer") for name in alive)
    assert not any(name.startswith("lwp-worker") for name in alive)


def test_close_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = make_services(tmp_path, monkeypatch)
    services.close()
    services.close()  # must not raise
