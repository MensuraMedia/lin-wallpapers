"""``TestVM`` — one real local image for the Test page (the right-click verification harness).

The Test page exists to prove that a real right-click opens a context menu on a plain, non-``FlowBox``
card. This gi-free view model supplies exactly one real local image so that card has something to show:
it tries the catalogue first (the first usable image, with its cached thumbnail bytes), and falls back
to the first readable image in a handful of standard picture directories when the catalogue is empty.
All filesystem work lives here, off the UI thread — the page and the card never touch a path or the disk.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from src.catalogue.queries import QuerySpec, fetch_page
from src.catalogue.thumbs import ThumbSize
from src.util.threads import Scheduler, run_in_worker
from src.viewmodels.services import AppServices

_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"})
_MAX_FILES_SCANNED = 4000  # a bounded look — this is a one-image demo source, not the scanner
_MAX_FILE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class TestImage:
    """One real local image: enough for the card to render it and the menu's *Details* to describe it."""

    __test__ = False  # not a pytest test class, despite the name

    path: str
    name: str
    width: int
    height: int
    data: bytes | None  # decodable JPEG/PNG/... bytes, or ``None`` when only a path is known


class TestVM:
    """Delivers a single :class:`TestImage` (or ``None``) off the UI thread.

    ``search_dirs`` are the fallback directories tried, in order, when the catalogue holds no image; the
    composition root passes them (so this module reads no environment variable itself).
    """

    __test__ = False  # not a pytest test class, despite the name

    def __init__(
        self,
        services: AppServices,
        search_dirs: Sequence[Path] = (),
        *,
        scheduler: Scheduler | None = None,
    ) -> None:
        self._services = services
        self._scheduler = scheduler if scheduler is not None else services.scheduler
        self._search_dirs = tuple(search_dirs)

    def load(self, cb: Callable[[TestImage | None], None]) -> object:
        """Find one image on a worker thread and deliver it (or ``None``) through the scheduler."""

        def work() -> TestImage | None:
            found = self._from_catalogue()
            return found if found is not None else self._from_disk()

        def done(result: TestImage | None, error: BaseException | None) -> None:
            cb(None if error is not None else result)

        return run_in_worker(work, done, scheduler=self._scheduler)

    # -- sources ---------------------------------------------------------------------------------------

    def _from_catalogue(self) -> TestImage | None:
        try:
            conn = self._services.read()
            page = fetch_page(conn, replace(QuerySpec(), limit=1, offset=0))
        except Exception:
            return None
        if not page.rows:
            return None
        row = page.rows[0]
        data: bytes | None = None
        if row.thumb_key is not None:
            data = self._services.thumbs.read(row.thumb_key, ThumbSize.NORMAL)
        return TestImage(row.path, row.name, row.width or 0, row.height or 0, data)

    def _from_disk(self) -> TestImage | None:
        examined = 0
        for base in self._search_dirs:
            for root, dirs, files in os.walk(base):
                dirs.sort()
                for name in sorted(files):
                    examined += 1
                    if examined > _MAX_FILES_SCANNED:
                        return None
                    path = Path(root) / name
                    if path.suffix.lower() not in _IMAGE_SUFFIXES:
                        continue
                    image = self._read(path)
                    if image is not None:
                        return image
        return None

    def _read(self, path: Path) -> TestImage | None:
        try:
            info = path.stat()
            if not path.is_file() or info.st_size > _MAX_FILE_BYTES:
                return None
            data = path.read_bytes()
        except OSError:
            return None
        size = _dimensions(data)
        if size is None:
            return None
        return TestImage(str(path), path.name, size[0], size[1], data)


def _dimensions(data: bytes) -> tuple[int, int] | None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            return (int(image.width), int(image.height))
    except Exception:
        return None
