"""Migration 1: the M1 schema, verbatim from ``schema.sql`` (frozen once released)."""

from __future__ import annotations

import sqlite3
from importlib import resources

from src.catalogue.migrations.script import run_script


def schema_sql() -> str:
    return resources.files("src.catalogue").joinpath("schema.sql").read_text(encoding="utf-8")


def apply(conn: sqlite3.Connection) -> None:
    run_script(conn, schema_sql())
