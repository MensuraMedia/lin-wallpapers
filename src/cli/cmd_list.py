"""``linwp list`` — the catalogued images, filtered like Browse (M1 §2.5/§2.9).

Flags map onto a :class:`~src.catalogue.queries.QuerySpec`: ``--ideal`` / ``--near-miss`` pick the segment,
``--display NAME`` narrows *ideal* to one output; ``--min-width`` / ``--min-height`` / ``--sort`` /
``--limit`` filter and order. ``score`` sort arrives in M2 and is a usage error until then. Text output
escapes control characters in paths so a hostile file name cannot forge a line.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import replace

from src.catalogue.queries import Segment, Sort, default_spec, fetch_page
from src.cli.context import Context, emit_json, emit_text, escape_control, warn

_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_USAGE = 2

_SORTS = {
    "name": Sort.NAME,
    "date": Sort.DATE_ADDED,
    "size": Sort.SIZE,
    "resolution": Sort.RESOLUTION,
}


def _display_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM display WHERE name = ? AND connected = 1 ORDER BY id LIMIT 1", (name,)
    ).fetchone()
    return None if row is None else int(row[0])


def run(args: argparse.Namespace, ctx: Context) -> int:
    conn = ctx.read()
    spec = default_spec(conn)

    if args.sort == "score":
        message = "sort 'score' arrives in M2"
        if args.json:
            emit_json({"ok": False, "error": "unsupported_sort", "detail": message})
        else:
            warn(f"linwp list: {message}")
        return _EXIT_USAGE

    changes: dict[str, object] = {}
    if args.ideal:
        changes["segment"] = Segment.IDEAL
    elif args.near_miss:
        changes["segment"] = Segment.NEAR_MISS

    if args.display:
        display_id = _display_id(conn, args.display)
        if display_id is None:
            if args.json:
                emit_json({"ok": False, "error": "no_such_display", "detail": args.display})
            else:
                warn(f"linwp list: no connected display named {args.display!r}")
            return _EXIT_ERROR
        changes["display_id"] = display_id

    if args.min_width is not None:
        changes["min_width"] = args.min_width
    if args.min_height is not None:
        changes["min_height"] = args.min_height
    if args.sort is not None:
        changes["sort"] = _SORTS[args.sort]
    if args.limit is not None:
        changes["limit"] = args.limit

    spec = replace(spec, **changes)  # type: ignore[arg-type]
    page = fetch_page(conn, spec)

    if args.json:
        emit_json(
            {
                "ok": True,
                "total": page.total,
                "offset": page.offset,
                "images": [
                    {
                        "id": row.id,
                        "path": row.path,
                        "width": row.width,
                        "height": row.height,
                        "format": row.format,
                        "size": row.size,
                        "missing": row.missing,
                        "probe_status": row.probe_status,
                    }
                    for row in page.rows
                ],
            }
        )
    else:
        emit_text(f"{page.total} image(s)")
        for row in page.rows:
            dims = f"{row.width}x{row.height}" if row.width and row.height else "?x?"
            flag = " (missing)" if row.missing else ""
            emit_text(f"{row.id:>6}  {dims:>11}  {escape_control(row.path)}{flag}")
    return _EXIT_OK
