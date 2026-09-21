"""Shared image render: the ONE transform that feeds both preview and apply.

``transform(path, size, fit)`` returns a Pillow image at exactly ``size`` so the
preview a user sees is byte-for-byte the render that gets applied (composite path).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Canonical fit modes used everywhere in the app.
FIT_FILL = "fill"  # cover: scale up, centre-crop (default)
FIT_FIT = "fit"  # contain: letterbox inside, pad with black
FIT_CENTER = "center"  # native size, centred, no scaling
FIT_STRETCH = "stretch"  # ignore aspect ratio

FITS: tuple[str, ...] = (FIT_FILL, FIT_FIT, FIT_CENTER, FIT_STRETCH)

# Human labels for the segmented control.
FIT_LABELS = {
    FIT_FILL: "Fill",
    FIT_FIT: "Fit",
    FIT_CENTER: "Center",
    FIT_STRETCH: "Stretch",
}

CACHE_DIR = Path.home() / ".cache" / "linwallpaper"
THUMB_DIR = CACHE_DIR / "thumbs"

_PAD = (18, 20, 26)  # letterbox / center pad colour (dark, matches surface)


def validate(path: str | os.PathLike) -> tuple[bool, str]:
    """Cheaply check that ``path`` is a decodable image.

    Returns ``(ok, reason)`` — ``reason`` is a short human string when not ok.
    Never raises: a missing, empty or corrupt file yields ``(False, ...)`` so
    callers can surface a toast instead of crashing.
    """
    p = Path(path)
    if not p.exists():
        return False, "file not found"
    if p.is_dir():
        return False, "that is a folder, not an image"
    try:
        with Image.open(p) as im:
            im.verify()  # header/format check without full decode
    except FileNotFoundError:
        return False, "file not found"
    except UnidentifiedImageError:
        return False, "not a supported image format"
    except (OSError, ValueError, SyntaxError):
        return False, "the image is corrupt or unreadable"
    return True, "ok"


def load(path: str | os.PathLike) -> Image.Image:
    """Load any image the system can decode, as RGB."""
    img = Image.open(path)
    img.load()
    if img.mode not in ("RGB",):
        img = img.convert("RGB")
    return img


def transform(path: str | os.PathLike, size: tuple[int, int], fit: str) -> Image.Image:
    """Render ``path`` into a new image of exactly ``size`` using ``fit``.

    This is the shared render for preview and (composite) apply.
    """
    if fit not in FITS:
        raise ValueError(f"unknown fit mode: {fit!r}")
    tw, th = int(size[0]), int(size[1])
    if tw <= 0 or th <= 0:
        raise ValueError("target size must be positive")
    src = load(path)

    if fit == FIT_STRETCH:
        return src.resize((tw, th), Image.LANCZOS)

    if fit == FIT_FILL:
        return _cover(src, tw, th)

    if fit == FIT_FIT:
        return _contain(src, tw, th)

    # FIT_CENTER: native pixels, centred, crop/pad as needed.
    canvas = Image.new("RGB", (tw, th), _PAD)
    ox = (tw - src.width) // 2
    oy = (th - src.height) // 2
    canvas.paste(src, (ox, oy))
    return canvas


def _cover(src: Image.Image, tw: int, th: int) -> Image.Image:
    scale = max(tw / src.width, th / src.height)
    nw, nh = max(1, round(src.width * scale)), max(1, round(src.height * scale))
    resized = src.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def _contain(src: Image.Image, tw: int, th: int) -> Image.Image:
    scale = min(tw / src.width, th / src.height)
    nw, nh = max(1, round(src.width * scale)), max(1, round(src.height * scale))
    resized = src.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (tw, th), _PAD)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def save_render(
    path: str | os.PathLike,
    size: tuple[int, int],
    fit: str,
    out_path: str | os.PathLike | None = None,
) -> str:
    """Render and save a PNG; returns the output path."""
    img = transform(path, size, fit)
    if out_path is None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(f"{path}|{size}|{fit}".encode()).hexdigest()[:12]
        out_path = CACHE_DIR / f"render-{digest}.png"
    img.save(out_path, "PNG")
    return str(out_path)


def thumbnail(path: str | os.PathLike, size: tuple[int, int] = (320, 200), fit: str = FIT_FILL) -> str:
    """Return a cached PNG thumbnail of ``path`` at ``size`` (rendered once).

    Keyed by path + mtime + size + fit, so a changed file re-renders and a
    Wallpaper-grid tile shows the *same* crop the apply would produce. Uses the
    shared ``transform`` (Pillow only — gi-free).
    """
    p = Path(path)
    try:
        mtime = int(p.stat().st_mtime)
    except OSError:
        mtime = 0
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"{p}|{mtime}|{size[0]}x{size[1]}|{fit}".encode()).hexdigest()[:16]
    out = THUMB_DIR / f"{digest}.png"
    if out.exists():
        return str(out)
    img = transform(path, size, fit)
    img.save(out, "PNG")
    return str(out)


def supported_formats() -> list[dict]:
    """Enumerate installed GdkPixbuf loaders -> list of {name, mime_types, extensions}.

    Built at runtime so the file filter matches exactly what the desktop can load.
    """
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    out: list[dict] = []
    for fmt in GdkPixbuf.Pixbuf.get_formats():
        out.append(
            {
                "name": fmt.get_name(),
                "mime_types": list(fmt.get_mime_types() or []),
                "extensions": list(fmt.get_extensions() or []),
            }
        )
    return out


def supported_mime_types() -> list[str]:
    """Flat, de-duplicated list of every mime type the pixbuf loaders accept."""
    seen: dict[str, None] = {}
    for fmt in supported_formats():
        for mime in fmt["mime_types"]:
            seen.setdefault(mime, None)
    return list(seen.keys())


def probe(path: str | os.PathLike) -> dict:
    """Cheap metadata for the info chips: filename, WxH, format."""
    img = Image.open(path)
    return {
        "name": Path(path).name,
        "width": img.width,
        "height": img.height,
        "format": (img.format or "").upper(),
    }
