"""``linwp displays`` — the displays this machine measures, and from where (M1 §2.9).

Re-detects the desktop (and persists it as the target set, exactly as a scan would), then prints the
displays and the probe attempts that produced them. ``--display WxH[,WxH...]`` adds declared displays;
junk there is a usage error (exit 2). When nothing can be detected the command still succeeds (exit 0):
the reason is in the JSON and the remedy is printed to stderr.
"""

from __future__ import annotations

import argparse

from src.cli.context import Context, emit_json, emit_text, warn
from src.scanner.displays import DisplaySpecError, parse_declared

_EXIT_OK = 0
_EXIT_USAGE = 2


def run(args: argparse.Namespace, ctx: Context) -> int:
    declared = []
    if getattr(args, "display", None):
        try:
            declared = list(parse_declared(args.display))
        except DisplaySpecError as error:
            if args.json:
                emit_json({"ok": False, "error": "bad_display", "detail": str(error)})
            else:
                warn(f"linwp displays: {error}")
            return _EXIT_USAGE

    detection = ctx.scan.refresh_displays(declared)

    displays = [
        {
            "name": d.name,
            "width": d.width,
            "height": d.height,
            "scale": d.scale,
            "primary": d.primary,
            "source": d.source.value,
        }
        for d in detection.displays
    ]
    attempts = [
        {"source": a.source.value, "ok": a.ok, "detail": a.detail} for a in detection.attempts
    ]
    payload: dict[str, object] = {"ok": True, "displays": displays, "attempts": attempts}
    if detection.reason is not None:
        payload["reason"] = {
            "code": detection.reason.code.value,
            "remedy": detection.reason.remedy,
        }

    if args.json:
        emit_json(payload)
    else:
        if displays:
            for d in displays:
                mark = " *" if d["primary"] else ""
                emit_text(f"{d['name']}  {d['width']}x{d['height']}  ({d['source']}){mark}")
        else:
            emit_text("no display detected")
        for attempt in attempts:
            state = "ok" if attempt["ok"] else "--"
            emit_text(f"  [{state}] {attempt['source']}: {attempt['detail']}")

    if detection.reason is not None:
        warn(f"no display detected — {detection.reason.remedy}")
    return _EXIT_OK
