"""``linwp show <id|path>`` — one image's metadata and its per-display verdicts (M1 §2.5/§2.9)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.catalogue.ideal import explain
from src.catalogue.queries import as_display, dims_of, get_image, verdicts_for
from src.cli.context import Context, emit_json, emit_text, escape_control

_EXIT_OK = 0
_EXIT_NOT_FOUND = 1


def _resolve(argument: str) -> int | str:
    if argument.isdigit():
        return int(argument)
    return str(Path(argument).expanduser().absolute())


def run(args: argparse.Namespace, ctx: Context) -> int:
    conn = ctx.read()
    image = get_image(conn, _resolve(args.image))
    if image is None:
        if args.json:
            emit_json({"ok": False, "error": "not_found", "detail": args.image})
        else:
            emit_text(f"no such image: {escape_control(args.image)}")
        return _EXIT_NOT_FOUND

    verdicts = verdicts_for(conn, image.id)

    if args.json:
        emit_json(
            {
                "ok": True,
                "id": image.id,
                "path": image.path,
                "width": image.width,
                "height": image.height,
                "format": image.format,
                "size": image.size,
                "probe_status": image.probe_status,
                "missing": image.missing,
                "excluded": image.excluded_by is not None,
                "thumb_status": image.thumb_status,
                "displays": [
                    {
                        "name": display.name,
                        "width": display.width,
                        "height": display.height,
                        "verdict": verdict.verdict.value,
                        "exact": verdict.exact,
                        "crop_loss": verdict.crop_loss,
                        "coverage": verdict.coverage,
                    }
                    for display, verdict in verdicts
                ],
            }
        )
    else:
        dims = f"{image.width}x{image.height}" if image.width and image.height else "unknown"
        emit_text(f"#{image.id}  {escape_control(image.path)}")
        emit_text(f"  {dims}  {image.format or '?'}  {image.probe_status}")
        if image.missing:
            emit_text("  (missing)")
        if image.excluded_by is not None:
            emit_text("  (excluded)")
        image_dims = dims_of(image)
        for display, verdict in verdicts:
            emit_text(f"  {display.name}: {explain(image_dims, as_display(display), verdict)}")
    return _EXIT_OK
