"""``AppServices`` — the GUI composition root, gi-free (M1 §2.9, ruling Q14).

This is the GUI twin of :mod:`src.cli.context`: it opens the catalogue once on the calling thread (to
migrate, seed the built-in groups and recover an interrupted scan), then wires the read connections, the
change feed, the thumbnail cache and the scan service around a single
:class:`~src.catalogue.ingest.CatalogueWriter`. Reads go through per-thread read-only connections on the
shared worker pool; every write goes through the writer thread. :meth:`close` joins the writer and stops
the worker pool, so nothing outlives the window (the no-daemon rule, contract §3).

Unlike ``context`` this module never imports ``gi`` — not even transitively — so it must **not** import
``gdk_displays`` (which reaches GTK). ``main.py`` (impl-J) builds ``[GdkDisplayProbe(), *service_probes(…)]``
and the ``glib_scheduler`` and injects both here; tests inject fake probes and ``immediate_scheduler``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

from src.catalogue.db import ChangeFeed, ReadConnections, open_catalogue
from src.catalogue.ingest import CatalogueWriter, ScanService
from src.catalogue.thumbs import ThumbCache
from src.config import config_paths
from src.scanner.displays import DisplayProbe
from src.scanner.roots import MountTable, load_mounts
from src.util import threads
from src.util.threads import Scheduler


class AppServices:
    """Everything the view models need, built once and closed once.

    Parameters
    ----------
    db_path:
        The catalogue file; ``None`` uses the configured default (``config_paths.catalogue_db()``).
    scheduler:
        Where worker results are delivered — ``glib_scheduler`` in the app, ``immediate_scheduler`` in
        tests. View models take this so they never import ``gi`` themselves.
    display_probes:
        The ordered probe chain, built by the caller (``main.py``) so this module never imports
        ``gdk_displays``. ``()`` (or fake probes) in tests.
    mounts:
        A callable returning the current :class:`MountTable`; defaults to ``load_mounts`` (findmnt).
    thumbs:
        Injectable so tests can point the cache at a tmp dir; defaults to the configured cache.
    """

    def __init__(
        self,
        db_path: Path | None,
        scheduler: Scheduler,
        display_probes: Sequence[DisplayProbe],
        mounts: Callable[[], MountTable] | None = None,
        *,
        thumbs: ThumbCache | None = None,
    ) -> None:
        path = Path(db_path) if db_path is not None else config_paths.catalogue_db()
        open_catalogue(path).close()  # migrate + seed + recover once here, then hand off to the writer
        self.db_path = path
        self.scheduler = scheduler
        self.mounts: Callable[[], MountTable] = mounts if mounts is not None else load_mounts
        self.feed = ChangeFeed()
        self.thumbs = thumbs if thumbs is not None else ThumbCache()
        self.writer = CatalogueWriter(path, self.feed)
        self.scan = ScanService(path, self.writer, self.thumbs, list(display_probes), self.mounts)
        self.reads = ReadConnections(path)

    def read(self) -> sqlite3.Connection:
        """This (worker) thread's read-only connection — call it from inside the worker job only."""
        return self.reads.get()

    def close(self) -> None:
        """Join the writer, stop the worker pool and refuse new read connections — no thread survives."""
        self.writer.close()
        threads.shutdown(wait=True)
        self.reads.close()
