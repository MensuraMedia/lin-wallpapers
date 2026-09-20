"""The CLI composition root and small shared output helpers (M1 §2.9).

``open_context`` builds, once per process, the objects every subcommand needs: it opens the catalogue on
the calling thread just long enough to migrate, seed the built-in groups and recover any interrupted scan
(``open_catalogue``), then wires the read connections, the change feed, the thumbnail cache and the scan
service around a single :class:`~src.catalogue.ingest.CatalogueWriter`. Reads go through per-thread
read-only connections; every write goes through the writer thread. ``close`` joins the writer so nothing is
left running.

No ``gi`` here (import-linter forbids it for ``src.cli``); the CLI only ever touches the service layers.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.catalogue.db import ChangeFeed, ReadConnections, open_catalogue
from src.catalogue.ingest import CatalogueWriter, ScanService
from src.catalogue.thumbs import ThumbCache
from src.config import config_paths
from src.scanner.displays import service_probes
from src.scanner.roots import load_mounts


@dataclass
class Context:
    """Everything a subcommand needs; closed by ``main`` in a ``finally``."""

    db_path: Path
    reads: ReadConnections
    feed: ChangeFeed
    thumbs: ThumbCache
    writer: CatalogueWriter
    scan: ScanService

    def read(self) -> sqlite3.Connection:
        """This thread's read-only connection."""
        return self.reads.get()

    def close(self) -> None:
        self.writer.close()
        self.reads.close()


def open_context(
    db_path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    root: Path = Path("/"),
) -> Context:
    path = Path(db_path) if db_path is not None else config_paths.catalogue_db()
    open_catalogue(path).close()  # migrate + seed + recover once, on this thread, then hand off to the writer
    feed = ChangeFeed()
    thumbs = ThumbCache()
    writer = CatalogueWriter(path, feed)
    environ = os.environ if env is None else env
    probes = service_probes(root, environ)
    scan = ScanService(path, writer, thumbs, probes, load_mounts)
    reads = ReadConnections(path)
    return Context(db_path=path, reads=reads, feed=feed, thumbs=thumbs, writer=writer, scan=scan)


# ── output helpers ───────────────────────────────────────────────────────────────────────────────────────

_CONTROL = {ord("\n"): "\\n", ord("\r"): "\\r", ord("\t"): "\\t"}


def escape_control(text: str) -> str:
    """Make a path safe to print on one line: newlines/tabs and other control characters are escaped, so a
    file literally named ``"a\\nb.jpg"`` cannot forge output lines."""
    out: list[str] = []
    for ch in text:
        if ch in "\n\r\t":
            out.append(_CONTROL[ord(ch)])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return "".join(out)


def emit_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def emit_text(line: str) -> None:
    print(line)


def warn(line: str) -> None:
    print(line, file=sys.stderr)
