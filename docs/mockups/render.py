#!/usr/bin/env python3
"""Render the .dc.html mockups to PNG screenshots.

The artboards are Design Component pages: their markup is plain static HTML inside <x-dc>, with a
<helmet> block for page-level styles, {{holes}} filled by the component's renderVals(), and
<dc-import> for the shared sidebar. This script resolves those three things and shoots each page
with headless Firefox, so the screenshots in docs/mockups/png/ stay reproducible.

    ./docs/mockups/render.py            # all artboards -> docs/mockups/png/
    ./docs/mockups/render.py Main       # one artboard

Needs: firefox (headless). Fonts come from Google Fonts when online; the fallback is Ubuntu/Cantarell.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "png"

# renderVals() of Sidebar.dc.html, per page
NAV = ("browse", "image", "screens", "preview", "history")
ACTIVE_BY_BOARD = {
    "Main": "browse",
    "Image": "image",
    "Screens": "screens",
    "Preview": "preview",
    "Apply": "history",
    "Sidebar": "browse",
}

# renderVals() of Preview.dc.html, "Mountain" preset
SCENE = {
    "scene.name": "mountain-distance-horizon.jpg",
    "scene.sky": "linear-gradient(170deg, #1B2A4A 0%, #3C6E9B 45%, #E9A05A 100%)",
    "scene.far": "#2C3E63",
    "scene.near": "#1B2440",
    "scene.sun": "#FFE1A6",
    "scene.sunOpacity": "0.92",
}


def sidebar_vals(active: str) -> dict[str, str]:
    vals = {}
    for key in NAV:
        on = key == active
        vals[f"st.{key}.bg"] = "rgba(255,199,0,0.14)" if on else "transparent"
        vals[f"st.{key}.fg"] = "#FFC700" if on else "#C7CBD6"
        vals[f"st.{key}.fw"] = "700" if on else "600"
    return vals


def fill(markup: str, vals: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        return vals.get(m.group(1).strip(), "")

    return re.sub(r"\{\{\s*([\w.$]+)\s*\}\}", sub, markup)


def parts(path: Path) -> tuple[str, str]:
    """(helmet contents, artboard markup) of a .dc.html file."""
    src = path.read_text()
    helmet = re.search(r"<helmet>(.*?)</helmet>", src, re.S)
    body = re.search(r"<x-dc>(.*?)</x-dc>", src, re.S)
    if not body:
        raise SystemExit(f"{path.name}: no <x-dc> block")
    markup = body.group(1)
    if helmet:
        markup = markup.replace(helmet.group(0), "")
    return (helmet.group(1) if helmet else ""), markup


def build(name: str) -> str:
    head, markup = parts(HERE / f"{name}.dc.html")
    sidebar_head, sidebar = parts(HERE / "Sidebar.dc.html")

    def mount(m: re.Match[str]) -> str:
        active = re.search(r'active="([^"]+)"', m.group(0))
        return fill(sidebar, sidebar_vals(active.group(1) if active else "browse"))

    markup = re.sub(r"<dc-import\b[^>]*></dc-import>", mount, markup)
    vals = {**SCENE, **sidebar_vals(ACTIVE_BY_BOARD.get(name, "browse"))}
    # Drop the webfont link: offline it stalls the headless render, and the fallback
    # (Ubuntu/Cantarell) is what the GTK app will use on the desktop anyway.
    head = re.sub(r"<link\b[^>]*fonts\.googleapis\.com[^>]*>", "", head)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"{head if head.strip() else sidebar_head}\n</head>\n<body>\n{fill(markup, vals)}\n</body>\n</html>\n"
    )


def size(name: str) -> tuple[int, int]:
    return (150, 800) if name == "Sidebar" else (1280, 800)


def main(argv: list[str]) -> int:
    firefox = shutil.which("firefox")
    if not firefox:
        print("firefox not found — install it or render the .dc.html files elsewhere", file=sys.stderr)
        return 1

    boards = argv[1:] or [p.stem.removesuffix(".dc") for p in sorted(HERE.glob("*.dc.html"))]
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "profile"
        profile.mkdir()
        for name in boards:
            page = Path(tmp) / f"{name}.html"
            page.write_text(build(name))
            png = OUT / f"{name}.png"
            w, h = size(name)
            subprocess.run(
                [
                    firefox, "--headless", "--no-remote",
                    "--profile", str(profile),
                    "--window-size", f"{w},{h}",
                    "--screenshot", str(png), page.as_uri(),
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )
            print(f"{png.relative_to(HERE.parent.parent)}  {w}x{h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
