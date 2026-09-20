"""Schema migrations, applied in order by ``src.catalogue.db.migrate`` (M1 contract §2.4).

Each migration runs inside ONE transaction that also bumps ``PRAGMA user_version``; ``apply`` must never
call ``executescript`` (it commits the open transaction) — use ``script.run_script``. A released migration
is frozen: schema changes are new entries at the end of ``MIGRATIONS``, numbered from 1 without gaps.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from src.catalogue.migrations import m0001_initial


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


MIGRATIONS: tuple[Migration, ...] = (Migration(1, "initial", m0001_initial.apply),)

__all__ = ["MIGRATIONS", "Migration"]
