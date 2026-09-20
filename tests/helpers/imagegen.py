"""Small, deterministic test images made with Pillow — no network, no fixtures in the repository.

Every ``make_*`` function takes the directory to write into and a plain file name, and returns the path
it wrote. A name with a directory part, or a directory that does not exist, is refused, so nothing is
ever written outside the (temporary) directory the test passed in. The same arguments always give the
same bytes. Pixels come from a coordinate gradient, or from ``random.Random(seed)`` when ``seed`` is
given — noise does not compress, which is how a test gets a file above the scanner's size minimum.
"""

from __future__ import annotations

import io
import random
import struct
import zlib
from pathlib import Path

from PIL import Image

Size = tuple[int, int]

DEFAULT_SIZE: Size = (64, 48)
EXIF_ORIENTATION_TAG = 0x0112
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _target(directory: Path, name: str) -> Path:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise ValueError(f"not a plain file name: {name!r}")
    if not directory.is_dir():
        raise ValueError(f"not an existing directory: {directory}")
    return directory / name


def _rgb(size: Size, seed: int | None = None, shift: int = 0) -> Image.Image:
    width, height = size
    if seed is not None:
        data = random.Random(seed).randbytes(width * height * 3)
    else:
        data = bytes(
            channel
            for y in range(height)
            for x in range(width)
            for channel in ((x * 4 + shift) % 256, (y * 4 + shift) % 256, (x + y + shift) % 256)
        )
    return Image.frombytes("RGB", size, data)


def _frames(size: Size, count: int) -> list[Image.Image]:
    if count < 2:
        raise ValueError("an animation needs at least two frames")
    return [_rgb(size, shift=index * 64) for index in range(count)]


def _encode(image: Image.Image, fmt: str, **options: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def _write(directory: Path, name: str, data: bytes) -> Path:
    path = _target(directory, name)
    path.write_bytes(data)
    return path


def make_jpeg(
    directory: Path, name: str = "plain.jpg", size: Size = DEFAULT_SIZE, *, seed: int | None = None
) -> Path:
    return _write(directory, name, _encode(_rgb(size, seed), "JPEG", quality=90))


def make_png(
    directory: Path, name: str = "plain.png", size: Size = DEFAULT_SIZE, *, seed: int | None = None
) -> Path:
    return _write(directory, name, _encode(_rgb(size, seed), "PNG"))


def make_webp(
    directory: Path, name: str = "plain.webp", size: Size = DEFAULT_SIZE, *, seed: int | None = None
) -> Path:
    return _write(directory, name, _encode(_rgb(size, seed), "WEBP", lossless=True))


def make_animated_gif(
    directory: Path, name: str = "animated.gif", size: Size = DEFAULT_SIZE, *, frames: int = 3
) -> Path:
    first, *rest = _frames(size, frames)
    return _write(
        directory, name, _encode(first, "GIF", save_all=True, append_images=rest, duration=100, loop=0)
    )


def make_animated_webp(
    directory: Path, name: str = "animated.webp", size: Size = DEFAULT_SIZE, *, frames: int = 3
) -> Path:
    first, *rest = _frames(size, frames)
    data = _encode(first, "WEBP", save_all=True, append_images=rest, duration=100, loop=0, lossless=True)
    return _write(directory, name, data)


def make_exif_rotated_jpeg(
    directory: Path, name: str = "rotated.jpg", size: Size = DEFAULT_SIZE, *, orientation: int = 6
) -> Path:
    """A JPEG whose stored pixels are ``size`` and whose EXIF orientation is 1..8 (5-8 swap the axes)."""
    if orientation not in range(1, 9):
        raise ValueError(f"EXIF orientation must be 1..8, got {orientation}")
    exif = Image.Exif()
    exif[EXIF_ORIENTATION_TAG] = orientation
    return _write(directory, name, _encode(_rgb(size), "JPEG", quality=90, exif=exif))


def make_cmyk_jpeg(directory: Path, name: str = "cmyk.jpg", size: Size = DEFAULT_SIZE) -> Path:
    return _write(directory, name, _encode(_rgb(size).convert("CMYK"), "JPEG", quality=90))


def make_png_16bit(directory: Path, name: str = "deep.png", size: Size = DEFAULT_SIZE) -> Path:
    """A 16-bit greyscale PNG (Pillow mode ``I;16``)."""
    width, height = size
    data = b"".join(
        struct.pack("<H", (x * 1021 + y * 517) % 65536) for y in range(height) for x in range(width)
    )
    return _write(directory, name, _encode(Image.frombytes("I;16", size, data), "PNG"))


def make_rgba_png(directory: Path, name: str = "alpha.png", size: Size = DEFAULT_SIZE) -> Path:
    """An RGBA PNG whose alpha channel really varies (a left-to-right ramp)."""
    image = _rgb(size).convert("RGBA")
    image.putalpha(Image.linear_gradient("L").rotate(90).resize(size))
    return _write(directory, name, _encode(image, "PNG"))


def make_palette_transparent_png(
    directory: Path, name: str = "palette.png", size: Size = DEFAULT_SIZE
) -> Path:
    """A palette (``P``) PNG with one fully transparent palette index (a ``tRNS`` chunk)."""
    image = _rgb(size).quantize(16)
    return _write(directory, name, _encode(image, "PNG", transparency=0))


def make_truncated_jpeg(
    directory: Path, name: str = "truncated.jpg", size: Size = DEFAULT_SIZE, *, keep: float = 0.5
) -> Path:
    return _write(directory, name, _cut(_encode(_rgb(size, seed=1), "JPEG", quality=90), keep))


def make_truncated_png(
    directory: Path, name: str = "truncated.png", size: Size = DEFAULT_SIZE, *, keep: float = 0.5
) -> Path:
    return _write(directory, name, _cut(_encode(_rgb(size, seed=1), "PNG"), keep))


def _cut(data: bytes, keep: float) -> bytes:
    """The leading ``keep`` fraction of ``data``: the header survives, the pixel data does not."""
    if not 0.0 < keep < 1.0:
        raise ValueError("keep must be strictly between 0 and 1")
    return data[: max(1, int(len(data) * keep))]


def make_zero_byte(directory: Path, name: str = "empty.jpg") -> Path:
    return _write(directory, name, b"")


def make_text_file(directory: Path, name: str = "notes.jpg") -> Path:
    """Plain text behind an image extension."""
    return _write(directory, name, b"this is not an image\n" * 8)


def make_png_huge_header(directory: Path, name: str = "huge.png", claimed: Size = (40_000, 40_000)) -> Path:
    """A tiny, well-formed PNG whose header claims ``claimed`` pixels; its pixel data is one short row."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", claimed[0], claimed[1], 8, 2, 0, 0, 0)  # 8-bit RGB, no interlace
    pixels = zlib.compress(b"\x00" * 64)
    return _write(
        directory, name, PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )
