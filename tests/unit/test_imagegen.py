"""The generated corpus has the properties its names claim — later probe tests depend on that."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from tests.helpers import imagegen

Maker = Callable[..., Path]

ALL_MAKERS: tuple[Maker, ...] = tuple(
    getattr(imagegen, name) for name in sorted(vars(imagegen)) if name.startswith("make_")
)


def _open(path: Path) -> Image.Image:
    return Image.open(path)


@pytest.mark.parametrize(
    ("maker", "fmt", "mode"),
    [
        (imagegen.make_jpeg, "JPEG", "RGB"),
        (imagegen.make_png, "PNG", "RGB"),
        (imagegen.make_webp, "WEBP", "RGB"),
    ],
)
def test_plain_images_decode_with_the_claimed_format_mode_and_size(
    maker: Maker, fmt: str, mode: str, tmp_path: Path
) -> None:
    path = maker(tmp_path, size=(80, 50))
    with _open(path) as image:
        image.load()
        assert (image.format, image.mode, image.size) == (fmt, mode, (80, 50))
        assert getattr(image, "n_frames", 1) == 1
        assert len(set(image.getdata())) > 1  # a real picture, not a flat fill


def test_a_seed_gives_incompressible_noise_for_size_thresholds(tmp_path: Path) -> None:
    flat = imagegen.make_png(tmp_path, "gradient.png", (256, 256))
    noisy = imagegen.make_png(tmp_path, "noise.png", (256, 256), seed=7)
    assert noisy.stat().st_size > 256 * 256 * 3 * 0.9
    assert noisy.stat().st_size > 64 * 1024 > flat.stat().st_size
    with _open(noisy) as image:
        image.load()
        assert image.size == (256, 256)


@pytest.mark.parametrize(
    ("maker", "fmt"), [(imagegen.make_animated_gif, "GIF"), (imagegen.make_animated_webp, "WEBP")]
)
def test_animations_have_several_distinct_frames(maker: Maker, fmt: str, tmp_path: Path) -> None:
    path = maker(tmp_path, frames=4)
    with _open(path) as image:
        assert image.format == fmt
        assert image.is_animated
        assert image.n_frames == 4
        frames = []
        for index in range(image.n_frames):
            image.seek(index)
            frames.append(image.convert("RGB").tobytes())
        assert len(set(frames)) == 4


def test_an_animation_needs_two_frames(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        imagegen.make_animated_gif(tmp_path, frames=1)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_exif_orientation_tag_is_present_and_pixels_are_stored_unrotated(
    orientation: int, tmp_path: Path
) -> None:
    path = imagegen.make_exif_rotated_jpeg(tmp_path, size=(64, 48), orientation=orientation)
    with _open(path) as image:
        assert image.format == "JPEG"
        assert image.size == (64, 48)
        assert image.getexif()[imagegen.EXIF_ORIENTATION_TAG] == orientation


def test_plain_jpeg_has_no_orientation_tag(tmp_path: Path) -> None:
    with _open(imagegen.make_jpeg(tmp_path)) as image:
        assert imagegen.EXIF_ORIENTATION_TAG not in image.getexif()


@pytest.mark.parametrize("orientation", [0, 9, -1])
def test_bad_orientation_is_refused(orientation: int, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        imagegen.make_exif_rotated_jpeg(tmp_path, orientation=orientation)


def test_cmyk_jpeg(tmp_path: Path) -> None:
    with _open(imagegen.make_cmyk_jpeg(tmp_path)) as image:
        image.load()
        assert (image.format, image.mode) == ("JPEG", "CMYK")


def test_16_bit_png_keeps_values_above_8_bits(tmp_path: Path) -> None:
    path = imagegen.make_png_16bit(tmp_path)
    with _open(path) as image:
        image.load()
        assert image.format == "PNG"
        assert image.mode in {
            "I",
            "I;16",
            "I;16B",
        }  # Pillow 10.2 widens 16-bit grey to "I"; later ones keep I;16
        assert image.getextrema()[1] > 255
    assert path.read_bytes()[24] == 16  # IHDR bit depth


def test_rgba_png_has_a_varying_alpha_channel(tmp_path: Path) -> None:
    with _open(imagegen.make_rgba_png(tmp_path)) as image:
        image.load()
        assert (image.format, image.mode) == ("PNG", "RGBA")
        low, high = image.getchannel("A").getextrema()
        assert low < 255
        assert high > low


def test_palette_png_carries_transparency(tmp_path: Path) -> None:
    with _open(imagegen.make_palette_transparent_png(tmp_path)) as image:
        image.load()
        assert (image.format, image.mode) == ("PNG", "P")
        assert image.info["transparency"] == 0


@pytest.mark.parametrize(
    ("maker", "fmt"), [(imagegen.make_truncated_jpeg, "JPEG"), (imagegen.make_truncated_png, "PNG")]
)
def test_truncated_files_open_lazily_but_fail_to_load(maker: Maker, fmt: str, tmp_path: Path) -> None:
    path = maker(tmp_path, size=(128, 96))
    with _open(path) as image:  # the header is intact …
        assert image.format == fmt
        assert image.size == (128, 96)
        with pytest.raises(OSError):  # … the pixel data is not
            image.load()


@pytest.mark.parametrize("keep", [0.0, 1.0, 1.5, -0.1])
def test_truncation_fraction_must_cut_something_and_keep_something(keep: float, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        imagegen.make_truncated_jpeg(tmp_path, keep=keep)


def test_zero_byte_file_is_empty_and_unopenable(tmp_path: Path) -> None:
    path = imagegen.make_zero_byte(tmp_path)
    assert path.stat().st_size == 0
    with pytest.raises(OSError):
        _open(path)


def test_text_file_with_an_image_extension_is_unopenable(tmp_path: Path) -> None:
    path = imagegen.make_text_file(tmp_path)
    assert path.suffix == ".jpg"
    assert path.stat().st_size > 0
    with pytest.raises(OSError):
        _open(path)


def test_huge_header_png_is_tiny_and_trips_pillows_own_bomb_guard(tmp_path: Path) -> None:
    path = imagegen.make_png_huge_header(tmp_path)
    assert path.stat().st_size < 1024
    assert path.read_bytes()[16:24] == (40_000).to_bytes(4, "big") * 2  # IHDR width, height
    with pytest.raises(Image.DecompressionBombError):  # Pillow's limit is left alone (ruling Q10)
        _open(path)


def test_large_header_png_below_pillows_hard_limit_reports_its_claimed_size(tmp_path: Path) -> None:
    path = imagegen.make_png_huge_header(tmp_path, claimed=(12_000, 10_000))
    with pytest.warns(Image.DecompressionBombWarning), _open(path) as image:
        # Lazy open reads the header only; nothing is decoded here.
        assert image.format == "PNG"
        assert image.size == (12_000, 10_000)


@pytest.mark.parametrize("maker", ALL_MAKERS, ids=lambda maker: maker.__name__)
def test_output_is_deterministic(maker: Maker, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    digests = {hashlib.sha256(maker(target).read_bytes()).hexdigest() for target in (first, second)}
    assert len(digests) == 1


@pytest.mark.parametrize("maker", ALL_MAKERS, ids=lambda maker: maker.__name__)
def test_each_maker_writes_exactly_one_file_in_the_given_directory(maker: Maker, tmp_path: Path) -> None:
    target = tmp_path / "out"
    target.mkdir()
    path = maker(target)
    assert path.parent == target
    assert [entry.name for entry in tmp_path.iterdir()] == ["out"]
    assert list(target.iterdir()) == [path]


@pytest.mark.parametrize("name", ["../escape.jpg", "sub/dir.jpg", "/abs.jpg", "", ".", ".."])
def test_names_that_could_leave_the_directory_are_refused(name: str, tmp_path: Path) -> None:
    target = tmp_path / "out"
    target.mkdir()
    with pytest.raises(ValueError):
        imagegen.make_jpeg(target, name)
    assert list(target.iterdir()) == []
    assert [entry.name for entry in tmp_path.iterdir()] == ["out"]


def test_a_missing_directory_is_refused_not_created(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        imagegen.make_png(tmp_path / "absent")
    assert list(tmp_path.iterdir()) == []


def test_unusual_but_plain_names_are_written_verbatim(tmp_path: Path) -> None:
    for name in ("with space.jpg", "new\nline.jpg", "ünï*[c]ode?.jpg"):
        assert imagegen.make_jpeg(tmp_path, name).name == name
    assert len(list(tmp_path.iterdir())) == 3
