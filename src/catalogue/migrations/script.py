"""Run a constant SQL script inside the caller's transaction.

``sqlite3.Connection.executescript`` commits any open transaction first, which would break the
"one transaction per migration" rule — so scripts are split with SQLite's own ``complete_statement``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator


def _is_blank(sql: str) -> bool:
    return all(not line.strip() or line.strip().startswith("--") for line in sql.splitlines())


def split_statements(script: str) -> Iterator[str]:
    start = 0
    position = script.find(";")
    while position != -1:
        candidate = script[start : position + 1]
        if sqlite3.complete_statement(candidate):
            yield candidate.strip()
            start = position + 1
        position = script.find(";", position + 1)
    if not _is_blank(script[start:]):
        raise ValueError("SQL script ends in an incomplete statement")


def run_script(conn: sqlite3.Connection, script: str) -> None:
    for statement in split_statements(script):
        conn.execute(statement)
