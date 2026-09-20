"""scanner/probe.py — opening a candidate file (contract §2.7, rulings Q10/Q10a/Q11/Q16).

``probe_file`` must never raise, however hostile the corpus: the ``tests/helpers/imagegen`` files
(truncated, zero-byte, CMYK, 16-bit, EXIF-swapped, animated, palette+transparency, a text file wearing a
``.jpg`` extension, a PNG header claiming 40000 × 40000 pixels) plus a FIFO, a vanished file and a file
that changes underneath the probe are all exercised here.
"""

from __future__ import annotations

import os
import struct
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from src.scanner.probe import (
    DecodeBudget,
    ProbeResult,
    ProbeStatus,
    content_key,
    probe_file,
    supported_formats,
)
from src.scanner.walker import Candidate, FileKey
from src.util.cancel import CancelToken
from tests.helpers import imagegen


def _key(path: Path) -> FileKey:
    st = path.stat()
    return (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)


def _candidate(path: Path, root: Path | None = None) -> Candidate:
    return Candidate(path=str(path), root=str(root if root is not None else path.parent), key=_key(path))


class RecordingSink:
    def __init__(self, result: str = "ok", *, raises: bool = False) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[Image.Image, str]] = []

    def store(self, image: Image.Image, key: str, cancel: CancelToken) -> str:
        self.calls.append((image, key))
        if self.raises:
            raise RuntimeError("thumbnail sink exploded")
        return self.result


BUDGET = DecodeBudget()


# ── the nasty corpus: every generator in tests/helpers/imagegen ────────────────────────────────────────


def test_plain_jpeg_is_ok(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.format == "JPEG"
    assert (result.width, result.height) == (64, 48)
    assert result.has_alpha is False
    assert result.is_animated is False


def test_plain_png_is_ok(tmp_path: Path) -> None:
    path = imagegen.make_png(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.format == "PNG"


def test_plain_webp_is_ok(tmp_path: Path) -> None:
    path = imagegen.make_webp(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.format == "WEBP"


def test_animated_gif_is_flagged_animated(tmp_path: Path) -> None:
    path = imagegen.make_animated_gif(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.is_animated is True
    assert result.format == "GIF"


def test_animated_webp_is_flagged_animated(tmp_path: Path) -> None:
    path = imagegen.make_animated_webp(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.is_animated is True


def test_exif_orientation_is_read_without_applying_it(tmp_path: Path) -> None:
    path = imagegen.make_exif_rotated_jpeg(tmp_path, orientation=6)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.exif_orientation == 6
    assert (result.width, result.height) == (64, 48)  # stored pixels, not the display orientation


def test_cmyk_jpeg_is_ok_and_not_alpha(tmp_path: Path) -> None:
    path = imagegen.make_cmyk_jpeg(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.has_alpha is False


def test_16bit_png_is_ok_regardless_of_pillow_mode_string(tmp_path: Path) -> None:
    """Ruling Q10a: 16-bit grey opens as Pillow mode ``"I"`` — never used to infer bit depth."""
    path = imagegen.make_png_16bit(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.format == "PNG"
    assert result.has_alpha is False


def test_rgba_png_has_alpha(tmp_path: Path) -> None:
    path = imagegen.make_rgba_png(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.has_alpha is True


def test_palette_transparent_png_has_alpha(tmp_path: Path) -> None:
    path = imagegen.make_palette_transparent_png(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.has_alpha is True


def test_truncated_jpeg_is_truncated(tmp_path: Path) -> None:
    path = imagegen.make_truncated_jpeg(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.TRUNCATED
    assert result.width and result.height  # the header survived the cut
    assert result.error


def test_truncated_png_is_truncated(tmp_path: Path) -> None:
    path = imagegen.make_truncated_png(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.TRUNCATED


def test_zero_byte_file_is_zero_byte(tmp_path: Path) -> None:
    path = imagegen.make_zero_byte(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.ZERO_BYTE
    assert result.width == 0 and result.height == 0


def test_text_file_named_dot_jpg_is_an_error_not_unsupported(tmp_path: Path) -> None:
    """JPEG *is* a supported format here — a text file wearing its extension is corrupt, not unsupported."""
    path = imagegen.make_text_file(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.ERROR
    assert result.error


# ── hostile magic bytes under an allowed extension ──────────────────────────────────────────────────────
#
# Pillow identifies a file by magic bytes, not by extension, so a corrupt-but-superficially-plausible file
# can reach a *foreign* plugin's ``_open()``. Pillow's own dispatcher (``PIL.Image._open_core``) only
# catches ``SyntaxError``/``IndexError``/``TypeError``/``struct.error`` between plugins and tries the next
# one; anything else — ``ValueError``, ``UnicodeDecodeError``, ... — is raised straight out of
# ``Image.open()``. ``probe_file`` must turn every one of these into a ``ProbeResult``, never let it escape.

_HOSTILE_MAGIC_BYTES: dict[str, bytes] = {
    # The adversary's repro: a PPM ("P5" magic) with a non-numeric header token -> ValueError.
    "ppm-as-png.png": b"P5\n2P5 999\n255\n\xff\xff",
    # An SGI-magic (big-endian short 474) header with a garbage body -> ValueError ("Unsupported SGI
    # image mode"), reached from a file named .jpg (SGI has no extension in common use).
    "sgi-as-jpg.jpg": struct.pack(">H", 474) + b"\xff" * 510,
    # An IM header whose "Image size (x*y)" value is not a number -> ValueError from IM's own `number()`.
    "im-as-png.png": b"Image size (x*y): abc,def\n\x1a" + b"\xff" * 20,
    # A "P5" (PPM) magic whose body is not valid UTF-8 -> UnicodeDecodeError.
    "ppm-unicode-as-jpg.jpg": b"P5\n" + b"\xff\xfe\x00" * 20,
}


@pytest.mark.parametrize(("name", "data"), sorted(_HOSTILE_MAGIC_BYTES.items()))
def test_hostile_magic_bytes_under_an_allowed_extension_never_raise(
    name: str, data: bytes, tmp_path: Path
) -> None:
    path = tmp_path / name
    path.write_bytes(data)
    result = probe_file(_candidate(path), BUDGET, RecordingSink(), CancelToken())
    assert result.status in (ProbeStatus.ERROR, ProbeStatus.UNSUPPORTED)
    assert result.error or result.status is ProbeStatus.UNSUPPORTED


def test_huge_header_is_too_large_with_null_dims_and_fast(tmp_path: Path) -> None:
    """Ruling Q11/Q10a: a header claiming 40000 x 40000 crosses Pillow's own bomb threshold inside
    ``Image.open()``, before ``.size`` can be read; no hand-rolled header parsing, no decode, and fast."""
    path = imagegen.make_png_huge_header(tmp_path, claimed=(40_000, 40_000))
    started = time.monotonic()
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    elapsed = time.monotonic() - started
    assert result.status is ProbeStatus.TOO_LARGE
    assert result.width == 0
    assert result.height == 0
    assert elapsed < 1.0


# ── over the app's own pixel budget, but under Pillow's bomb threshold ─────────────────────────────────


def test_over_pixel_budget_is_recorded_with_dims_and_no_decode(tmp_path: Path) -> None:
    """Between our budget (100 MP) and Pillow's own bomb error (~179 MP) Pillow only *warns*; that warning
    must not surface, the header dims are still recorded, and there is no decode (a fast return)."""
    claimed = (12_000, 10_000)  # 120,000,000 px: over our default budget, under Pillow's hard limit
    path = imagegen.make_png_huge_header(tmp_path, name="over-budget.png", claimed=claimed)
    started = time.monotonic()
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    elapsed = time.monotonic() - started
    assert result.status is ProbeStatus.OVER_BUDGET
    assert (result.width, result.height) == claimed
    assert elapsed < 1.0


def test_jpeg_gets_a_larger_pixel_budget_than_other_formats() -> None:
    budget = DecodeBudget()
    assert budget.max_jpeg_pixels > budget.max_pixels


def test_a_budget_under_the_images_pixels_still_allows_a_smaller_image(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path, size=(64, 48))
    tight_budget = DecodeBudget(max_pixels=64 * 48, max_jpeg_pixels=64 * 48)
    result = probe_file(_candidate(path), tight_budget, None, CancelToken())
    assert result.status is ProbeStatus.OK  # exactly at the budget: not over it
    tighter = DecodeBudget(max_pixels=64 * 48 - 1, max_jpeg_pixels=64 * 48 - 1)
    over = probe_file(_candidate(path), tighter, None, CancelToken())
    assert over.status is ProbeStatus.OVER_BUDGET


# ── over max_file_bytes: a large-on-disk, unreadable file must still return fast ────────────────────────


def test_a_very_large_unidentifiable_file_returns_fast(tmp_path: Path) -> None:
    """A sparse file far bigger than any walker would have admitted, in case one ever reaches probe_file
    anyway (a TOCTOU growth after the walker's own size check): format sniffing reads only the header."""
    path = tmp_path / "huge.jpg"
    with path.open("wb") as handle:
        handle.truncate(300 * 1024 * 1024)  # sparse: no real disk I/O for the bulk of it
    started = time.monotonic()
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    elapsed = time.monotonic() - started
    assert result.status is ProbeStatus.ERROR
    assert elapsed < 2.0


# ── races: the file changes or vanishes around the probe ───────────────────────────────────────────────


def test_file_replaced_during_probe_reports_the_fds_own_key(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path, size=(64, 48))
    stale_candidate = _candidate(path)  # the walker's view, before the replacement below
    imagegen.make_png(tmp_path, name=path.name, size=(80, 60))  # overwritten with different content+format

    result = probe_file(stale_candidate, BUDGET, None, CancelToken())

    assert result.key != stale_candidate.key  # re-read from the fd, not trusted from the walker
    assert result.key == _key(path)
    assert result.status is ProbeStatus.OK
    assert result.format == "PNG"  # what is actually there now, not what the walker once saw


def test_vanished_before_open_is_an_error_not_a_raise(tmp_path: Path) -> None:
    path = tmp_path / "ghost.jpg"
    path.write_bytes(b"x" * 100)
    candidate = _candidate(path)
    path.unlink()

    result = probe_file(candidate, BUDGET, None, CancelToken())

    assert result.status is ProbeStatus.ERROR
    assert result.key == candidate.key  # nothing better was ever available
    assert result.error


def test_a_fifo_is_an_error_and_does_not_hang(tmp_path: Path) -> None:
    path = tmp_path / "pipe.jpg"
    os.mkfifo(path)
    st = path.stat()
    candidate = Candidate(path=str(path), root=str(tmp_path), key=(st.st_dev, st.st_ino, 0, 0))

    started = time.monotonic()
    result = probe_file(candidate, BUDGET, None, CancelToken())
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    assert result.status is ProbeStatus.ERROR


# ── thumbnailing ─────────────────────────────────────────────────────────────────────────────────────────


def test_successful_probe_stores_a_thumbnail(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path)
    sink = RecordingSink(result="ok")
    result = probe_file(_candidate(path), BUDGET, sink, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.thumb_status == "ok"
    assert result.thumb_key is not None
    assert len(sink.calls) == 1


def test_a_raising_thumb_sink_never_escapes_probe_file(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path)
    sink = RecordingSink(raises=True)
    result = probe_file(_candidate(path), BUDGET, sink, CancelToken())
    assert result.status is ProbeStatus.OK  # the decode itself still succeeded
    assert result.thumb_status == "failed"


def test_no_thumb_sink_leaves_thumb_fields_unset(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path)
    result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    assert result.thumb_key is None
    assert result.thumb_status is None


def test_over_budget_and_too_large_never_reach_the_thumb_sink(tmp_path: Path) -> None:
    over = imagegen.make_png_huge_header(tmp_path, name="a.png", claimed=(12_000, 10_000))
    too_large = imagegen.make_png_huge_header(tmp_path, name="b.png", claimed=(40_000, 40_000))
    sink = RecordingSink()
    for path in (over, too_large):
        probe_file(_candidate(path), BUDGET, sink, CancelToken())
    assert sink.calls == []


# ── the seconds budget is cooperative, not a hard guard (D12) ──────────────────────────────────────────


def test_an_already_exceeded_time_budget_does_not_fail_a_valid_decode(tmp_path: Path) -> None:
    """A slow header read (thread contention, a loaded disk) must never turn a valid image into a spurious
    ERROR: the pixel/byte caps are the hard guard, the seconds budget is only ever cooperative (D12)."""
    path = imagegen.make_jpeg(tmp_path)
    sink = RecordingSink()
    spent_budget = DecodeBudget(max_seconds=0.0)  # exceeded by the time any real work has happened

    result = probe_file(_candidate(path), spent_budget, sink, CancelToken())

    assert result.status is ProbeStatus.OK  # the decode itself is never skipped on time alone
    assert (result.width, result.height) == (64, 48)


def test_an_already_exceeded_time_budget_skips_only_the_optional_thumbnail(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path)
    sink = RecordingSink()
    spent_budget = DecodeBudget(max_seconds=0.0)

    result = probe_file(_candidate(path), spent_budget, sink, CancelToken())

    assert result.status is ProbeStatus.OK
    assert result.thumb_key is None
    assert result.thumb_status is None
    assert sink.calls == []  # the extra, avoidable work is what gets skipped, never the probe result itself


def test_a_generous_time_budget_still_produces_a_thumbnail(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path)
    sink = RecordingSink()
    result = probe_file(_candidate(path), DecodeBudget(max_seconds=5.0), sink, CancelToken())
    assert result.status is ProbeStatus.OK
    assert result.thumb_status == "ok"
    assert len(sink.calls) == 1


# ── content_key ──────────────────────────────────────────────────────────────────────────────────────────


def test_content_key_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"hello world" * 100)
    fd = os.open(path, os.O_RDONLY)
    try:
        first = content_key(fd, path.stat().st_size)
        second = content_key(fd, path.stat().st_size)
    finally:
        os.close(fd)
    assert first == second
    assert len(first) == 32  # 128-bit digest, hex


def test_content_key_differs_when_content_differs(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    a.write_bytes(b"a" * 1000)
    b = tmp_path / "b.bin"
    b.write_bytes(b"b" * 1000)
    fd_a, fd_b = os.open(a, os.O_RDONLY), os.open(b, os.O_RDONLY)
    try:
        assert content_key(fd_a, 1000) != content_key(fd_b, 1000)
    finally:
        os.close(fd_a)
        os.close(fd_b)


def test_content_key_handles_files_smaller_than_the_head_and_tail_windows(tmp_path: Path) -> None:
    path = tmp_path / "tiny.bin"
    path.write_bytes(b"hi")
    fd = os.open(path, os.O_RDONLY)
    try:
        key = content_key(fd, 2)
    finally:
        os.close(fd)
    assert len(key) == 32


def test_content_key_of_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    fd = os.open(path, os.O_RDONLY)
    try:
        key = content_key(fd, 0)
    finally:
        os.close(fd)
    assert len(key) == 32


# ── supported_formats ────────────────────────────────────────────────────────────────────────────────────


def test_supported_formats_reports_the_common_formats_as_available() -> None:
    formats = supported_formats()
    for name in ("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"):
        assert formats[name] is True


def test_supported_formats_is_a_plain_bool_mapping() -> None:
    formats = supported_formats()
    assert all(isinstance(value, bool) for value in formats.values())


# ── never raises, over the whole corpus ─────────────────────────────────────────────────────────────────

_MAKERS = tuple(getattr(imagegen, name) for name in sorted(vars(imagegen)) if name.startswith("make_"))


@pytest.mark.parametrize("maker", _MAKERS, ids=lambda maker: maker.__name__)
def test_probe_file_never_raises_over_the_corpus(maker: Callable[[Path], Path], tmp_path: Path) -> None:
    path = maker(tmp_path)
    result = probe_file(_candidate(path), BUDGET, RecordingSink(), CancelToken())
    assert isinstance(result, ProbeResult)
    assert isinstance(result.status, ProbeStatus)


def test_probe_file_never_raises_on_a_directory_masquerading_as_a_file(tmp_path: Path) -> None:
    fake = tmp_path / "not-really.jpg"
    fake.mkdir()
    st = fake.stat()
    candidate = Candidate(path=str(fake), root=str(tmp_path), key=(st.st_dev, st.st_ino, 0, 0))
    result = probe_file(candidate, BUDGET, None, CancelToken())
    assert result.status is ProbeStatus.ERROR


def test_probe_file_never_raises_on_a_permission_denied_path(tmp_path: Path) -> None:
    path = imagegen.make_jpeg(tmp_path)
    path.chmod(0o000)
    try:
        result = probe_file(_candidate(path), BUDGET, None, CancelToken())
    finally:
        path.chmod(0o644)
    assert result.status is ProbeStatus.ERROR
