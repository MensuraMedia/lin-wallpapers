"""``catalogue/thumbs.py``: the sharded, budgeted thumbnail cache (M1 contract §2.8)."""

from __future__ import annotations

import io
import os
import stat
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from src.catalogue.thumbs import ThumbCache, ThumbSize
from src.util.cancel import Cancelled, CancelToken
from tests.helpers.imagegen import (
    make_exif_rotated_jpeg,
    make_jpeg,
    make_palette_transparent_png,
)

BAD_KEYS = [
    "",
    "short",
    "F" * 32,  # uppercase
    "g" * 32,  # not hex
    "0" * 31,  # too short
    "0" * 33,  # too long
    "0" * 31 + "/",  # path separator
    "../" + "0" * 29,
]


def _key(n: int) -> str:
    """A deterministic, always-valid 32 hex digit key."""
    return f"{n:032x}"


@pytest.fixture
def cache(tmp_path: Path) -> ThumbCache:
    return ThumbCache(base=tmp_path / "thumbs")


# ── path layout, key validation ──────────────────────────────────────────────────────────────────────────


def test_sharded_layout_matches_the_contract(cache: ThumbCache, tmp_path: Path) -> None:
    key = _key(1)
    normal = cache.path_for(key, ThumbSize.NORMAL)
    large = cache.path_for(key, ThumbSize.LARGE)
    assert normal == tmp_path / "thumbs" / "normal" / key[:2] / f"{key}.jpg"
    assert large == tmp_path / "thumbs" / "large" / key[:2] / f"{key}.jpg"


def test_path_for_is_a_pure_function_of_key_and_size(cache: ThumbCache) -> None:
    key = _key(2)
    assert cache.path_for(key, ThumbSize.NORMAL) == cache.path_for(key, ThumbSize.NORMAL)
    assert cache.path_for(key, ThumbSize.NORMAL) != cache.path_for(key, ThumbSize.LARGE)


def test_different_content_keys_never_collide(cache: ThumbCache) -> None:
    assert cache.path_for(_key(3), ThumbSize.NORMAL) != cache.path_for(_key(4), ThumbSize.NORMAL)


@pytest.mark.parametrize("bad_key", BAD_KEYS)
def test_path_for_rejects_bad_keys_before_any_filesystem_access(tmp_path: Path, bad_key: str) -> None:
    base = tmp_path / "thumbs"
    cache = ThumbCache(base=base)
    with pytest.raises(ValueError):
        cache.path_for(bad_key, ThumbSize.NORMAL)
    assert not base.exists()


def test_store_rejects_a_bad_key_before_any_filesystem_access(tmp_path: Path) -> None:
    base = tmp_path / "thumbs"
    cache = ThumbCache(base=base)
    image = Image.new("RGB", (10, 10))
    with pytest.raises(ValueError):
        cache.store(image, "not-hex-at-all", CancelToken())
    assert not base.exists()


def test_read_rejects_a_bad_key_before_any_filesystem_access(tmp_path: Path) -> None:
    base = tmp_path / "thumbs"
    cache = ThumbCache(base=base)
    with pytest.raises(ValueError):
        cache.read("BAD")
    assert not base.exists()


def test_ensure_large_rejects_a_bad_key_before_any_filesystem_access(tmp_path: Path) -> None:
    base = tmp_path / "thumbs"
    cache = ThumbCache(base=base)
    with pytest.raises(ValueError):
        cache.ensure_large(Path("/nonexistent/src.jpg"), "BAD" * 20)
    assert not base.exists()


# ── store / read: key stability, content addressing ──────────────────────────────────────────────────────


def test_key_is_stable_across_a_simulated_move_or_rename(cache: ThumbCache, tmp_path: Path) -> None:
    """The cache slot depends only on the key, never on where the source file lives."""
    key = _key(5)
    original = make_jpeg(tmp_path, "before.jpg", size=(40, 30), seed=1)
    with Image.open(original) as image:
        cache.store(image, key, CancelToken())
    first_read = cache.read(key)
    assert first_read is not None

    # "rename": store again under the same key from a different path but identical content
    moved = make_jpeg(tmp_path, "after.jpg", size=(40, 30), seed=1)
    with Image.open(moved) as image:
        result = cache.store(image, key, CancelToken())
    assert result == "ok"
    assert cache.read(key) == first_read  # unchanged: the same key is a no-op, wherever the source is


def test_a_different_key_produces_different_bytes_at_a_different_path(
    cache: ThumbCache, tmp_path: Path
) -> None:
    key_a, key_b = _key(6), _key(7)
    image_a = make_jpeg(tmp_path, "a.jpg", size=(40, 30), seed=1)
    image_b = make_jpeg(tmp_path, "b.jpg", size=(40, 30), seed=2)
    with Image.open(image_a) as image:
        cache.store(image, key_a, CancelToken())
    with Image.open(image_b) as image:
        cache.store(image, key_b, CancelToken())
    assert cache.path_for(key_a, ThumbSize.NORMAL) != cache.path_for(key_b, ThumbSize.NORMAL)
    assert cache.read(key_a) != cache.read(key_b)


def test_store_is_a_no_op_when_the_key_already_exists(cache: ThumbCache, tmp_path: Path) -> None:
    key = _key(8)
    first = make_jpeg(tmp_path, "one.jpg", size=(40, 30), seed=1)
    second = make_jpeg(tmp_path, "two.jpg", size=(40, 30), seed=99)
    with Image.open(first) as image:
        assert cache.store(image, key, CancelToken()) == "ok"
    before = cache.read(key)
    with Image.open(second) as image:
        assert cache.store(image, key, CancelToken()) == "ok"
    assert cache.read(key) == before  # the second (different) image never overwrote the first


def test_store_raises_cancelled_when_the_token_is_already_cancelled(
    cache: ThumbCache, tmp_path: Path
) -> None:
    token = CancelToken()
    token.cancel()
    source = make_jpeg(tmp_path, "c.jpg")
    with Image.open(source) as image, pytest.raises(Cancelled):
        cache.store(image, _key(9), token)


# ── atomic write ─────────────────────────────────────────────────────────────────────────────────────────


def test_atomic_write_leaves_no_tmp_file_after_a_simulated_failure(
    cache: ThumbCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _key(10)
    source = make_jpeg(tmp_path, "s.jpg", size=(50, 40))

    def boom(_src: str | os.PathLike[str], _dst: str | os.PathLike[str]) -> None:
        raise OSError("simulated failure mid-write")

    monkeypatch.setattr(os, "replace", boom)
    with Image.open(source) as image:
        result = cache.store(image, key, CancelToken())
    assert result == "failed"
    target = cache.path_for(key, ThumbSize.NORMAL)
    assert not target.exists()
    assert list(target.parent.glob("*.tmp")) == []


def test_write_atomic_treats_a_late_arriving_target_as_success(
    cache: ThumbCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If our own replace fails but the target now exists — a concurrent writer for the same key finished
    first, after ``store()``'s initial existence check but before ours — that is success, not 'failed'."""
    key = _key(230)
    target = cache.path_for(key, ThumbSize.NORMAL)
    target.parent.mkdir(parents=True, mode=0o700)
    winner_bytes = b"written by the concurrent winner"

    def boom(_src: str | os.PathLike[str], _dst: str | os.PathLike[str]) -> None:
        target.write_bytes(winner_bytes)  # the other writer finishes between our write and our replace
        raise OSError("simulated replace failure after a concurrent writer already finished")

    monkeypatch.setattr(os, "replace", boom)
    image = Image.new("RGB", (10, 10), (1, 2, 3))
    cache._write_atomic(image, target)  # must not raise
    assert target.read_bytes() == winner_bytes  # the winner's bytes were left untouched
    assert list(target.parent.glob("*.tmp")) == []


def test_store_creates_directories_with_private_permissions(cache: ThumbCache, tmp_path: Path) -> None:
    key = _key(11)
    source = make_jpeg(tmp_path, "p.jpg")
    with Image.open(source) as image:
        cache.store(image, key, CancelToken())
    target = cache.path_for(key, ThumbSize.NORMAL)
    for directory in (target.parent, target.parent.parent, target.parent.parent.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_store_is_race_safe_when_many_threads_share_a_new_shard_directory(tmp_path: Path) -> None:
    """A scan-private pool of probe threads (M1 contract §3) calls ``store()`` concurrently and routinely
    lands on the same brand-new shard directory (``key[:2]``) at once. Directory creation is TOCTOU by
    nature (``_ensure_private_dir``), so a losing thread's ``mkdir`` must not surface as ``'failed'``."""
    base = tmp_path / "thumbs"
    cache = ThumbCache(base=base)
    assert not base.exists()  # nothing pre-created: every worker races to make base/normal/<shard>

    worker_count = 16
    keys = [_key(200 + i) for i in range(worker_count)]
    assert len({key[:2] for key in keys}) == 1  # _key()'s zero-padding: they all share shard "00"

    sources = [make_jpeg(tmp_path, f"race{i}.jpg", size=(60, 40), seed=i) for i in range(worker_count)]
    results: list[str] = [""] * worker_count
    barrier = threading.Barrier(worker_count)

    def worker(index: int) -> None:
        with Image.open(sources[index]) as image:
            image.load()
            barrier.wait()  # line every thread up so the mkdir race is as tight as possible
            results[index] = cache.store(image, keys[index], CancelToken())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == ["ok"] * worker_count  # none lost the mkdir race as a 'failed' store

    shard_dir = cache.path_for(keys[0], ThumbSize.NORMAL).parent
    for directory in (base, base / "normal", shard_dir):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700  # whichever thread won is still private
    for key in keys:
        assert cache.read(key) is not None


def test_store_is_race_safe_when_many_threads_share_the_same_content_key(tmp_path: Path) -> None:
    """Two files with identical ``content_key()`` (duplicate content — the walker only dedups by
    ``(device, inode)``, never by content) can be probed concurrently and both call ``store()`` with the
    same key. They must not share one ``*.tmp`` file: the loser of a shared name would see its own
    ``os.replace`` raise ``FileNotFoundError`` against a path the winner already moved away, and the
    resulting 'failed' would be persisted forever as ``image.thumb_status`` for a thumbnail that in fact
    exists. Concurrent, interleaved writes into one shared temp file could also corrupt it outright."""
    base = tmp_path / "thumbs"
    cache = ThumbCache(base=base)
    key = _key(210)
    source = make_jpeg(tmp_path, "shared.jpg", size=(220, 160), seed=5)

    worker_count = 8
    results: list[str] = [""] * worker_count
    barrier = threading.Barrier(worker_count)

    def worker(index: int) -> None:
        with Image.open(source) as image:
            image.load()
            barrier.wait()  # line every thread up so the tmp-file race is as tight as possible
            results[index] = cache.store(image, key, CancelToken())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == ["ok"] * worker_count  # none lost the tmp race as a 'failed' store

    target = cache.path_for(key, ThumbSize.NORMAL)
    assert target.exists()
    data = cache.read(key)
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:  # the final file is a valid, undamaged JPEG
        out.load()
        assert out.size[0] > 0 and out.size[1] > 0
    assert list(target.parent.glob("*.tmp")) == []  # no writer's temp file was left behind


# ── no upscaling ─────────────────────────────────────────────────────────────────────────────────────────


def test_store_never_upscales_a_small_source(cache: ThumbCache, tmp_path: Path) -> None:
    key = _key(12)
    small = make_jpeg(tmp_path, "small.jpg", size=(100, 60))
    with Image.open(small) as image:
        cache.store(image, key, CancelToken())
    data = cache.read(key)
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert out.width <= 100
        assert out.height <= 60


def test_store_shrinks_a_large_source_to_the_long_edge(cache: ThumbCache, tmp_path: Path) -> None:
    key = _key(13)
    large = make_jpeg(tmp_path, "large.jpg", size=(1000, 500))
    with Image.open(large) as image:
        cache.store(image, key, CancelToken())
    data = cache.read(key)
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert max(out.size) == int(ThumbSize.NORMAL)
        assert out.width > out.height  # aspect ratio preserved


# ── alpha flattening, ICC, EXIF ──────────────────────────────────────────────────────────────────────────


def test_store_flattens_alpha_onto_mid_grey(cache: ThumbCache) -> None:
    image = Image.new("RGBA", (10, 10), (255, 0, 0, 0))  # fully transparent
    cache.store(image, _key(14), CancelToken())
    data = cache.read(_key(14))
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert out.mode == "RGB"
        r, g, b = out.convert("RGB").getpixel((5, 5))
        assert abs(r - 128) <= 6 and abs(g - 128) <= 6 and abs(b - 128) <= 6


def test_store_converts_a_non_alpha_non_rgb_mode_to_rgb(cache: ThumbCache) -> None:
    image = Image.new("L", (20, 20), 128)  # grayscale, no alpha
    cache.store(image, _key(90), CancelToken())
    data = cache.read(_key(90))
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert out.mode == "RGB"


def test_store_handles_palette_images_with_transparency(cache: ThumbCache, tmp_path: Path) -> None:
    source = make_palette_transparent_png(tmp_path, "pal.png", size=(32, 32))
    with Image.open(source) as image:
        assert cache.store(image, _key(15), CancelToken()) == "ok"
    data = cache.read(_key(15))
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert out.mode == "RGB"


def test_store_applies_exif_orientation(cache: ThumbCache, tmp_path: Path) -> None:
    # orientation 6 swaps the axes; the source is smaller than NORMAL on both edges, so no resize occurs.
    source = make_exif_rotated_jpeg(tmp_path, "rot.jpg", size=(80, 40), orientation=6)
    with Image.open(source) as image:
        cache.store(image, _key(16), CancelToken())
    data = cache.read(_key(16))
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert (out.width, out.height) == (40, 80)


def test_store_drops_the_icc_profile_after_converting_to_srgb(cache: ThumbCache, tmp_path: Path) -> None:
    from PIL import ImageCms

    icc_bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = tmp_path / "icc.jpg"
    Image.new("RGB", (40, 30), (10, 20, 30)).save(path, format="JPEG", icc_profile=icc_bytes)
    with Image.open(path) as image:
        assert "icc_profile" in image.info
        cache.store(image, _key(17), CancelToken())
    data = cache.read(_key(17))
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert "icc_profile" not in out.info


def test_store_drops_a_broken_icc_profile_without_crashing(cache: ThumbCache, tmp_path: Path) -> None:
    path = tmp_path / "badicc.jpg"
    Image.new("RGB", (40, 30), (5, 6, 7)).save(path, format="JPEG", icc_profile=b"not a real profile")
    with Image.open(path) as image:
        assert cache.store(image, _key(18), CancelToken()) == "ok"
    data = cache.read(_key(18))
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert "icc_profile" not in out.info


# ── read: LRU clock ──────────────────────────────────────────────────────────────────────────────────────


def test_read_of_a_missing_key_returns_none(cache: ThumbCache) -> None:
    assert cache.read(_key(19)) is None


def test_read_touches_mtime_at_most_once_a_day(cache: ThumbCache, tmp_path: Path) -> None:
    key = _key(20)
    source = make_jpeg(tmp_path, "m.jpg")
    with Image.open(source) as image:
        cache.store(image, key, CancelToken())
    path = cache.path_for(key, ThumbSize.NORMAL)
    stale = time.time() - 90_000  # more than a day old
    os.utime(path, (stale, stale))

    cache.read(key)
    touched = path.stat().st_mtime
    assert touched > stale + 60_000  # bumped forward to "now"

    cache.read(key)
    assert path.stat().st_mtime == pytest.approx(touched, abs=5)  # not bumped again so soon after


# ── ensure_large ─────────────────────────────────────────────────────────────────────────────────────────


def test_ensure_large_builds_the_512_thumbnail_lazily_from_the_source(
    cache: ThumbCache, tmp_path: Path
) -> None:
    key = _key(21)
    source = make_jpeg(tmp_path, "big.jpg", size=(1000, 700), seed=3)
    with Image.open(source) as image:
        cache.store(image, key, CancelToken())  # NORMAL only during a scan
    assert cache.read(key, ThumbSize.LARGE) is None

    before_usage = cache.usage()
    data = cache.ensure_large(source, key)
    assert data is not None
    assert cache.usage() > before_usage
    with Image.open(io.BytesIO(data)) as out:
        assert max(out.size) == int(ThumbSize.LARGE)

    again = cache.ensure_large(source, key)  # already built: reused, not rebuilt
    assert again == data


def test_ensure_large_never_upscales(cache: ThumbCache, tmp_path: Path) -> None:
    key = _key(22)
    source = make_jpeg(tmp_path, "small.jpg", size=(90, 70))
    data = cache.ensure_large(source, key)
    assert data is not None
    with Image.open(io.BytesIO(data)) as out:
        assert out.width <= 90
        assert out.height <= 70


def test_ensure_large_returns_none_when_the_source_is_missing(cache: ThumbCache, tmp_path: Path) -> None:
    assert cache.ensure_large(tmp_path / "nope.jpg", _key(23)) is None


# ── usage / clear ────────────────────────────────────────────────────────────────────────────────────────


def test_usage_and_clear_on_an_empty_cache(tmp_path: Path) -> None:
    cache = ThumbCache(base=tmp_path / "thumbs")
    assert cache.usage() == 0
    assert cache.clear() == 0


def test_usage_reflects_stored_bytes_and_clear_empties_the_cache(cache: ThumbCache, tmp_path: Path) -> None:
    key = _key(24)
    source = make_jpeg(tmp_path, "u.jpg", size=(120, 90))
    with Image.open(source) as image:
        cache.store(image, key, CancelToken())
    usage_before = cache.usage()
    assert usage_before > 0

    freed = cache.clear()
    assert freed == usage_before
    assert cache.usage() == 0
    assert cache.read(key) is None


# ── eviction ─────────────────────────────────────────────────────────────────────────────────────────────


def test_evict_is_a_no_op_when_already_under_budget(tmp_path: Path) -> None:
    base = tmp_path / "thumbs"
    cache = ThumbCache(base=base, budget_bytes=10**9)
    source = make_jpeg(tmp_path, "one.jpg", size=(100, 80))
    key = _key(25)
    with Image.open(source) as image:
        cache.store(image, key, CancelToken())
    assert cache.evict() == 0
    assert cache.path_for(key, ThumbSize.NORMAL).exists()


def test_evict_removes_the_oldest_thumbnails_first_down_to_ninety_percent(tmp_path: Path) -> None:
    base = tmp_path / "thumbs"
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    seed_cache = ThumbCache(base=base, budget_bytes=10**9)  # generous: store() ignores the budget anyway
    keys = [_key(30 + i) for i in range(5)]
    for i, key in enumerate(keys):
        source = make_jpeg(source_dir, f"{i}.jpg", size=(220, 160), seed=i)
        with Image.open(source) as image:
            seed_cache.store(image, key, CancelToken())
    paths = [seed_cache.path_for(key, ThumbSize.NORMAL) for key in keys]

    now = time.time()
    for rank, path in enumerate(paths):  # rank 0 = oldest, rank -1 = newest
        stamp = now - (len(paths) - rank) * 1_000
        os.utime(path, (stamp, stamp))

    total = seed_cache.usage()
    budget = int(total * 0.6)  # comfortably below total: forces eviction, but not of everything
    cache = ThumbCache(base=base, budget_bytes=budget)
    freed = cache.evict()

    assert freed > 0
    assert cache.usage() <= int(budget * 0.9)

    remaining_ranks = [rank for rank, path in enumerate(paths) if path.exists()]
    removed_ranks = [rank for rank, path in enumerate(paths) if not path.exists()]
    assert removed_ranks, "expected at least one thumbnail to be evicted"
    if remaining_ranks:
        assert max(removed_ranks) < min(remaining_ranks)  # only ever the oldest ones are gone


def test_evict_target_is_pinned_at_ninety_percent_of_the_budget(tmp_path: Path) -> None:
    """Regression guard for the 90% constant itself.

    Five equal-sized thumbnails (same source, same seed, stored under different keys) make the eviction
    levels exact multiples of one unit: 5, 4, 3, 2, 1, 0 units. With ``budget = 2.1 units``, a 90% target
    (``1.89 units``) must remove down to 1 unit remaining, while a 100% target (``2.1 units``) would stop
    one file earlier, at 2 units. So mutating ``_EVICT_TARGET_FRACTION`` from 0.9 to 1.0 changes both the
    number of files removed and the final usage — this test fails under that mutation.
    """
    base = tmp_path / "thumbs"
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    seed_cache = ThumbCache(base=base, budget_bytes=10**9)
    keys = [_key(120 + i) for i in range(5)]
    source = make_jpeg(source_dir, "identical.jpg", size=(220, 160), seed=42)  # one source, equal sizes
    for key in keys:
        with Image.open(source) as image:
            seed_cache.store(image, key, CancelToken())
    paths = [seed_cache.path_for(key, ThumbSize.NORMAL) for key in keys]
    sizes = {path.stat().st_size for path in paths}
    assert len(sizes) == 1, "fixture bug: the five thumbnails must be byte-identical in size"
    unit = sizes.pop()

    now = time.time()
    for rank, path in enumerate(paths):  # rank 0 = oldest .. rank -1 = newest
        stamp = now - (len(paths) - rank) * 1_000
        os.utime(path, (stamp, stamp))

    budget = int(unit * 2.1)  # comfortably inside [2 units, 2.222 units): see docstring
    cache = ThumbCache(base=base, budget_bytes=budget)
    freed = cache.evict()

    assert freed == 4 * unit  # a 100%-of-budget target would only free 3 units, leaving 2 not 1
    assert cache.usage() == unit
    assert [path.exists() for path in paths] == [False, False, False, False, True]  # only the newest


# ── defensive OSError paths (races against another process/thread) ─────────────────────────────────────


def test_usage_skips_a_file_that_vanishes_between_listing_and_stat(
    cache: ThumbCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _key(91)
    source = make_jpeg(tmp_path, "v.jpg")
    with Image.open(source) as image:
        cache.store(image, key, CancelToken())
    target = cache.path_for(key, ThumbSize.NORMAL)
    original_stat = Path.stat

    def flaky_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if self == target:
            raise OSError("vanished before stat")
        return original_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    assert cache.usage() == 0


def test_touch_is_silent_when_the_file_vanishes_before_stat(
    cache: ThumbCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _key(92)
    source = make_jpeg(tmp_path, "t.jpg")
    with Image.open(source) as image:
        cache.store(image, key, CancelToken())
    target = cache.path_for(key, ThumbSize.NORMAL)
    original_stat = Path.stat

    def flaky_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if self == target:
            raise OSError("vanished before stat")
        return original_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    assert cache.read(key) is not None  # read_bytes() still succeeds; _touch() swallows the stat error


def test_evict_skips_a_file_that_fails_to_unlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "thumbs"
    seed_cache = ThumbCache(base=base, budget_bytes=10**9)
    keys = [_key(100 + i) for i in range(3)]
    for i, key in enumerate(keys):
        source = make_jpeg(tmp_path, f"e{i}.jpg", size=(200, 150), seed=i)
        with Image.open(source) as image:
            seed_cache.store(image, key, CancelToken())
    paths = [seed_cache.path_for(key, ThumbSize.NORMAL) for key in keys]
    now = time.time()
    for rank, path in enumerate(paths):
        stamp = now - (len(paths) - rank) * 1_000
        os.utime(path, (stamp, stamp))

    total = seed_cache.usage()
    budget = int(total * 0.3)
    cache = ThumbCache(base=base, budget_bytes=budget)

    original_unlink = Path.unlink
    unremovable = paths[0]  # the oldest — evict() tries this one first

    def flaky_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == unremovable:
            raise OSError("cannot remove")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    freed = cache.evict()
    assert unremovable.exists()  # the failed unlink left it in place
    assert freed >= 0


# ── the cache lives only under a (temporary) XDG cache dir ──────────────────────────────────────────────


def test_default_base_stays_under_the_temporary_xdg_cache_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    cache = ThumbCache()
    path = cache.path_for(_key(40), ThumbSize.NORMAL)
    assert path.is_relative_to(tmp_path / "xdg-cache" / "lin-wallpapers" / "thumbnails")


def test_default_base_falls_back_under_a_temporary_home_without_xdg_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    cache = ThumbCache()
    path = cache.path_for(_key(41), ThumbSize.NORMAL)
    assert path.is_relative_to(fake_home / ".cache" / "lin-wallpapers" / "thumbnails")
