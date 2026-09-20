"""``linwp scan [--add PATH] [--display WxH[,WxH...]]`` — a real scan (M1 §2.9, ruling Q17).

``--add PATH`` registers a permanent, enabled ``RootKind.USER`` root (mirroring the GUI "Add folder"),
then scans. ``--display`` declares one or more unconnected displays to also judge for; junk there is a
usage error (exit 2). ``SIGINT`` cancels the running scan and exits 130. When no display can be detected
the scan still succeeds (exit 0): the reason is in the JSON and the remedy is printed to stderr.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import signal
import sqlite3
from pathlib import Path
from types import FrameType

from src.catalogue.db import Change, ChangeKind
from src.catalogue.ingest import ScanProgress, ScanSummary
from src.cli.context import Context, emit_json, emit_text, warn
from src.scanner.displays import Display, DisplaySpecError, parse_declared
from src.util.cancel import CancelToken
from src.util.threads import immediate_scheduler, run_in_worker

_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_USAGE = 2
_EXIT_SIGINT = 130


class _SilentListener:
    def on_progress(self, p: ScanProgress) -> None:
        return None


def _add_root(ctx: Context, path: str) -> int:
    absolute = str(Path(path).expanduser().absolute())

    def job(conn: sqlite3.Connection) -> int:
        existing = conn.execute("SELECT id FROM root WHERE path = ?", (absolute,)).fetchone()
        if existing is not None:
            conn.execute("UPDATE root SET enabled = 1 WHERE id = ?", (existing[0],))
            return int(existing[0])
        cursor = conn.execute(
            "INSERT INTO root(path, kind, enabled) VALUES (?, 'user', 1)", (absolute,)
        )
        return int(cursor.lastrowid or 0)

    root_id = ctx.writer.submit(job).result()
    ctx.feed.emit(Change(ChangeKind.ROOTS_CHANGED))
    return root_id


def _scan_error(ctx: Context, scan_id: int) -> str | None:
    """The class name of the failure recorded on a scan row (``reason`` = ``{"error": "<Class>", …}``)."""
    row = ctx.read().execute("SELECT reason FROM scan WHERE id = ?", (scan_id,)).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        data = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    name = data.get("error") if isinstance(data, dict) else None
    return name if isinstance(name, str) else None


def _run(ctx: Context, declared: list[Display]) -> ScanSummary:
    cancel = CancelToken()

    def handler(_signum: int, _frame: FrameType | None) -> None:
        cancel.cancel()

    previous = signal.signal(signal.SIGINT, handler)
    try:
        future = run_in_worker(
            lambda: ctx.scan.scan(None, declared, _SilentListener(), cancel),
            scheduler=immediate_scheduler,
        )
        while True:
            try:
                return future.result(timeout=0.2)
            except concurrent.futures.TimeoutError:
                continue
    finally:
        signal.signal(signal.SIGINT, previous)


def run(args: argparse.Namespace, ctx: Context) -> int:
    try:
        declared = list(parse_declared(args.display)) if args.display else []
    except DisplaySpecError as error:
        if args.json:
            emit_json({"ok": False, "error": "bad_display", "detail": str(error)})
        else:
            warn(f"linwp scan: {error}")
        return _EXIT_USAGE

    if args.add:
        _add_root(ctx, args.add)

    summary = _run(ctx, declared)

    if summary.result == "error":
        # a writer job failed mid-scan (locked/corrupt/full catalogue): the pipeline recorded the failure on
        # the scan row, and §2.9 requires a catalogue error to exit 1 with its class name (not a silent 0).
        error_name = _scan_error(ctx, summary.scan_id) or "CatalogueError"
        if args.json:
            emit_json(
                {"ok": False, "error": error_name, "scan_id": summary.scan_id, "result": "error"}
            )
        else:
            warn(f"linwp scan: {error_name}")
        return _EXIT_ERROR

    progress = summary.progress
    detection = summary.detection

    displays = [
        {"name": d.name, "width": d.width, "height": d.height, "source": d.source.value}
        for d in detection.displays
    ]
    payload: dict[str, object] = {
        "ok": True,
        "scan_id": summary.scan_id,
        "result": summary.result,
        "dirs": progress.dirs,
        "found": progress.found,
        "probed": progress.probed,
        "unchanged": progress.unchanged,
        "ideal": progress.ideal,
        "excluded": progress.excluded,
        "issues": progress.issues,
        "displays": displays,
    }
    if detection.reason is not None:
        payload["reason"] = {
            "code": detection.reason.code.value,
            "remedy": detection.reason.remedy,
        }

    if args.json:
        emit_json(payload)
    else:
        emit_text(
            f"scan {summary.scan_id}: {summary.result} — "
            f"{progress.found} found, {progress.probed} probed, {progress.unchanged} unchanged, "
            f"{progress.ideal} ideal, {progress.excluded} excluded, {progress.issues} issues "
            f"({progress.dirs} dirs, {summary.seconds:.1f}s)"
        )
        if displays:
            names = ", ".join(f"{d['name']} {d['width']}x{d['height']}" for d in displays)
            emit_text(f"displays: {names}")

    if detection.reason is not None:
        warn(f"no display detected — {detection.reason.remedy}")

    if summary.result == "cancelled":
        return _EXIT_SIGINT
    return _EXIT_OK
