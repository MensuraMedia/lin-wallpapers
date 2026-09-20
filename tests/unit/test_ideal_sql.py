"""The SQL side of the ideal segment: rebuild ≡ evaluate, pins, sub-segments, display changes, speed."""

from __future__ import annotations

import builtins
import io
import os
import random
import sqlite3
import time
from pathlib import Path

import pytest

from src.catalogue import db, ideal, queries
from src.catalogue.ideal import ImageDims, Verdict
from src.catalogue.queries import QuerySpec, Segment
from src.scanner.displays import Display, DisplayDetection
from tests.unit.test_catalogue_support import FHD, PORTRAIT, UHD, add_image, detection, open_db, set_displays

SEED = 20260918


def names(conn: sqlite3.Connection, **spec: object) -> list[str]:
    return [row.name for row in queries.fetch_page(conn, QuerySpec(**spec)).rows]  # type: ignore[arg-type]


# ── Python ≡ SQL ─────────────────────────────────────────────────────────────────────────────────────────


def _boundary_images(display: Display, threshold: int) -> list[tuple[int, int]]:
    big_w, big_h = display.width, display.height
    out: list[tuple[int, int]] = []
    for dw in (-1, 0, 1):
        for dh in (-1, 0, 1):
            out.append((big_w + dw, big_h + dh))  # covers / exact boundary
            out.append(((9 * big_w + 9) // 10 + dw, (9 * big_h + 9) // 10 + dh))  # 90 % coverage boundary
    for keep in (100 - threshold, 75):  # crop boundaries: h fixed, w where 100·W·h = keep·w·H and vice versa
        h = big_h * 2
        if keep:
            wide = (100 * big_w * h) // (keep * big_h)
            narrow = (keep * big_w * h) // (100 * big_h)
            out += [(wide + d, h) for d in (-1, 0, 1)] + [(narrow + d, h) for d in (-1, 0, 1)]
    return out


def test_sql_rebuild_agrees_with_evaluate_on_a_random_grid(tmp_path: Path) -> None:
    rng = random.Random(SEED)
    conn = open_db(tmp_path)
    displays = [Display(f"rand-{n}", rng.randint(320, 7680), rng.randint(320, 4320)) for n in range(12)]
    displays += [
        FHD,
        UHD,
        PORTRAIT,
        Display("sq", 2000, 2000),
        Display("uw", 3440, 1440),
        Display("tiny", 1, 1),
    ]
    ids = set_displays(conn, *displays)
    by_id = {
        row["id"]: Display(row["name"], row["width"], row["height"])
        for row in conn.execute("SELECT id, name, width, height FROM display")
    }
    assert sorted(by_id) == ids

    thresholds = [0, 1, 10, 15, 16, 25, 40]
    images: dict[int, ImageDims] = {}
    shapes: list[tuple[int | None, int | None]] = []
    for display in displays:
        for threshold in thresholds:
            shapes += _boundary_images(display, threshold)
    shapes += [(rng.randint(1, 9000), rng.randint(1, 9000)) for _ in range(400)]
    shapes += [
        (0, 0),
        (0, 1080),
        (1920, 0),
        (-1920, -1080),
        (None, None),
        (1920, None),
        (2_000_000, 1_125_000),
    ]
    shapes = list(dict.fromkeys(shapes))
    with db.transaction(conn):
        for index, (w, h) in enumerate(shapes):
            roll = rng.random()
            alpha, animated = roll < 0.05, 0.05 <= roll < 0.10
            status = (
                rng.choice(["truncated", "too_large", "over_budget", "error"])
                if 0.10 <= roll < 0.15
                else "ok"
            )
            image_id = add_image(
                conn,
                f"/p/{index}.jpg",
                w,
                h,
                has_alpha=int(alpha),
                is_animated=int(animated),
                probe_status=status,
            )
            images[image_id] = ImageDims(
                w if w is not None else 0, h if h is not None else 0, alpha, animated, status == "ok"
            )

    cases = 0
    for threshold in thresholds:
        ideal.rebuild(conn, threshold)
        stored = {
            (row["image_id"], row["display_id"]): row
            for row in conn.execute(
                "SELECT image_id, display_id, verdict, exact, crop_loss, coverage FROM ideal_image"
            )
        }
        for image_id, dims in images.items():
            for display_id, display in by_id.items():
                expected = ideal.evaluate(dims, display, threshold)
                row = stored.get((image_id, display_id))
                got = Verdict.NO if row is None else Verdict(row["verdict"])
                assert got is expected.verdict, (dims, display, threshold)
                if row is not None:
                    assert bool(row["exact"]) is expected.exact
                    assert row["crop_loss"] == pytest.approx(expected.crop_loss, abs=1e-12)
                    assert row["coverage"] == pytest.approx(expected.coverage, abs=1e-12)
                cases += 1
    assert cases > 3000
    assert {Verdict(v) for (v,) in conn.execute("SELECT DISTINCT verdict FROM ideal_image")} == {
        Verdict.IDEAL,
        Verdict.NEAR,
    }


def test_incremental_rebuild_equals_full_rebuild(tmp_path: Path) -> None:
    rng = random.Random(SEED + 1)
    conn = open_db(tmp_path)
    set_displays(conn, FHD, UHD)
    with db.transaction(conn):
        ids = [
            add_image(conn, f"/p/{n}.jpg", rng.randint(1500, 4200), rng.randint(900, 2400))
            for n in range(300)
        ]
    for start in range(0, len(ids), 70):
        ideal.rebuild(conn, 16, ids[start : start + 70])
    dump = "SELECT image_id, display_id, verdict, exact, crop_loss, coverage FROM ideal_image ORDER BY 1, 2"
    incremental = [tuple(row) for row in conn.execute(dump)]
    written = ideal.rebuild(conn, 16)
    assert incremental == [tuple(row) for row in conn.execute(dump)]
    assert written == len(incremental) > 0
    # an image that changed is re-judged, the others are untouched
    conn.execute("UPDATE image SET width = 10, height = 10 WHERE id = ?", (ids[0],))
    ideal.rebuild(conn, 16, [ids[0]])
    assert conn.execute("SELECT count(*) FROM ideal_image WHERE image_id = ?", (ids[0],)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM ideal_image").fetchone()[0] in (
        len(incremental),
        len(incremental) - 1,
        len(incremental) - 2,
    )
    assert ideal.rebuild(conn, 16, []) == 0


def test_rebuild_rejects_a_bad_threshold_and_changes_nothing(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    set_displays(conn, FHD)
    add_image(conn, "/p/a.jpg", 1920, 1080)
    ideal.rebuild(conn, 16)
    for bad in (-1, 41, "16; DROP TABLE image"):
        with pytest.raises(ValueError):
            ideal.rebuild(conn, bad)  # type: ignore[arg-type]
    assert conn.execute("SELECT count(*) FROM ideal_image").fetchone()[0] == 1


def test_threshold_change_moves_images_between_ideal_and_near(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    set_displays(conn, FHD)
    add_image(conn, "/p/three-two.jpg", 3000, 2000)
    ideal.rebuild(conn, 16)
    assert names(conn, segment=Segment.IDEAL) == ["three-two.jpg"]
    ideal.rebuild(conn, 15)
    assert names(conn, segment=Segment.IDEAL) == []
    assert names(conn, segment=Segment.NEAR_MISS) == ["three-two.jpg"]


# ── sub-segments ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def two_screens(tmp_path: Path) -> tuple[sqlite3.Connection, int, int]:
    conn = open_db(tmp_path)
    fhd, uhd = set_displays(conn, FHD, UHD)
    add_image(conn, "/p/exact-fhd.jpg", 1920, 1080)
    add_image(conn, "/p/exact-uhd.jpg", 3840, 2160)
    add_image(conn, "/p/big.jpg", 5120, 2880)
    add_image(conn, "/p/mid.jpg", 2560, 1440)
    add_image(conn, "/p/near-fhd.jpg", 1760, 990)
    add_image(conn, "/p/four-three.jpg", 4000, 3000)  # 25 % crop: near for both
    add_image(conn, "/p/icon.jpg", 64, 36)
    add_image(conn, "/p/portrait.jpg", 2160, 3840)
    add_image(conn, "/p/alpha.png", 3840, 2160, has_alpha=1)
    add_image(conn, "/p/anim.gif", 3840, 2160, is_animated=1)
    add_image(conn, "/p/trunc.jpg", 3840, 2160, probe_status="truncated")
    add_image(conn, "/p/bomb.png", None, None, probe_status="too_large")
    ideal.rebuild(conn, 16)
    return conn, fhd, uhd


def test_ideal_for_this_desktop_means_any_target_display(
    two_screens: tuple[sqlite3.Connection, int, int],
) -> None:
    conn, _fhd, _uhd = two_screens
    assert names(conn, segment=Segment.IDEAL) == ["big.jpg", "exact-fhd.jpg", "exact-uhd.jpg", "mid.jpg"]


def test_every_display_per_display_exact_larger_and_near(
    two_screens: tuple[sqlite3.Connection, int, int],
) -> None:
    conn, fhd, uhd = two_screens
    assert names(conn, segment=Segment.IDEAL, every_display=True) == ["big.jpg", "exact-uhd.jpg"]
    assert names(conn, segment=Segment.IDEAL, display_id=fhd) == [
        "big.jpg",
        "exact-fhd.jpg",
        "exact-uhd.jpg",
        "mid.jpg",
    ]
    assert names(conn, segment=Segment.IDEAL, display_id=uhd) == ["big.jpg", "exact-uhd.jpg"]
    assert names(conn, segment=Segment.IDEAL, exact=True) == ["exact-fhd.jpg", "exact-uhd.jpg"]
    assert names(conn, segment=Segment.IDEAL, exact=True, display_id=uhd) == ["exact-uhd.jpg"]
    assert names(conn, segment=Segment.IDEAL, exact=False) == ["big.jpg", "exact-uhd.jpg", "mid.jpg"]
    assert names(conn, segment=Segment.IDEAL, exact=False, display_id=uhd) == ["big.jpg"]
    assert names(conn, segment=Segment.IDEAL, exact=True, every_display=True) == []
    # near misses sit OUTSIDE the segment: nothing ideal for another display shows up here
    assert names(conn, segment=Segment.NEAR_MISS) == ["four-three.jpg", "near-fhd.jpg"]
    assert names(conn, segment=Segment.NEAR_MISS, display_id=fhd) == ["four-three.jpg", "near-fhd.jpg"]
    assert names(conn, segment=Segment.NEAR_MISS, display_id=uhd) == ["four-three.jpg"]
    assert names(conn, segment=Segment.IDEAL, display_id=999_999) == []


def test_segment_counts(two_screens: tuple[sqlite3.Connection, int, int]) -> None:
    conn, fhd, uhd = two_screens
    assert queries.segment_counts(conn) == {
        "all": 10,  # usable rows only: trunc.jpg and bomb.png are hidden by default
        "ideal": 4,
        "near": 2,
        "exact": 2,
        "larger": 3,
        "every": 2,
        f"display:{fhd}": 4,
        f"display:{uhd}": 2,
    }
    narrowed = queries.segment_counts(conn, QuerySpec(search="exact"))
    assert (narrowed["all"], narrowed["ideal"], narrowed["every"]) == (2, 2, 1)


def test_integrity_failures_and_null_dimensions_are_never_members(
    two_screens: tuple[sqlite3.Connection, int, int],
) -> None:
    conn, _fhd, _uhd = two_screens
    judged = {
        row[0]
        for row in conn.execute("SELECT DISTINCT i.name FROM ideal_image x JOIN image i ON i.id = x.image_id")
    }
    assert judged.isdisjoint({"alpha.png", "anim.gif", "trunc.jpg", "bomb.png", "icon.jpg", "portrait.jpg"})
    everything = names(conn, segment=Segment.IDEAL, include_unusable=True, include_excluded=True)
    assert "trunc.jpg" not in everything and "bomb.png" not in everything


def test_verdicts_for_lists_every_target_display_primary_first(
    two_screens: tuple[sqlite3.Connection, int, int],
) -> None:
    conn, _fhd, _uhd = two_screens
    image = queries.get_image(conn, "/p/mid.jpg")
    assert image is not None
    verdicts = queries.verdicts_for(conn, image.id)
    assert [(d.name, v.verdict) for d, v in verdicts] == [("eDP-1", Verdict.IDEAL), ("HDMI-A-1", Verdict.NO)]
    assert verdicts[1][1].failed == (ideal.Test.COVERS,)
    bomb = queries.get_image(conn, "/p/bomb.png")
    assert bomb is not None
    assert all(v.verdict is Verdict.NO for _d, v in queries.verdicts_for(conn, bomb.id))
    assert queries.verdicts_for(conn, 987_654) == []
    # the stored threshold is honoured; a tampered one falls back to the default
    three_two = add_image(conn, "/p/three-two.jpg", 3000, 2000)
    db.set_setting(conn, "ideal.threshold_pct", 15)
    assert queries.verdicts_for(conn, three_two)[0][1].verdict is Verdict.NEAR
    db.set_setting(conn, "ideal.threshold_pct", 4000)
    assert queries.verdicts_for(conn, three_two)[0][1].verdict is Verdict.IDEAL


def test_excluded_and_missing_are_filtered_at_query_time_without_a_rebuild(
    two_screens: tuple[sqlite3.Connection, int, int],
) -> None:
    conn, _fhd, _uhd = two_screens
    rule = db.add_rule(conn, db.RuleKind.FOLDER, "/elsewhere", group=None, root=None)
    rows_before = conn.execute("SELECT count(*) FROM ideal_image").fetchone()[0]
    conn.execute("UPDATE image SET excluded_by = ? WHERE name = 'big.jpg'", (rule,))
    conn.execute("UPDATE image SET missing = 1 WHERE name = 'mid.jpg'")
    conn.execute("UPDATE image SET missing = 1 WHERE name = 'near-fhd.jpg'")
    assert names(conn, segment=Segment.IDEAL) == ["exact-fhd.jpg", "exact-uhd.jpg"]
    assert names(conn, segment=Segment.IDEAL, include_excluded=True, missing=True) == [
        "exact-fhd.jpg",
        "exact-uhd.jpg",
    ]
    assert names(conn, segment=Segment.NEAR_MISS) == ["four-three.jpg"]
    assert conn.execute("SELECT count(*) FROM ideal_image").fetchone()[0] == rows_before  # derived rows kept
    conn.execute("UPDATE image SET excluded_by = NULL, missing = 0")
    assert names(conn, segment=Segment.IDEAL) == ["big.jpg", "exact-fhd.jpg", "exact-uhd.jpg", "mid.jpg"]


# ── pins ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_pins_survive_rebuilds_and_display_changes(two_screens: tuple[sqlite3.Connection, int, int]) -> None:
    conn, fhd, _uhd = two_screens
    icon = queries.get_image(conn, "/p/icon.jpg")
    big = queries.get_image(conn, "/p/big.jpg")
    near = queries.get_image(conn, "/p/near-fhd.jpg")
    assert icon and big and near
    ideal.set_pin(conn, icon.id, "in")
    ideal.set_pin(conn, near.id, "in")
    ideal.set_pin(conn, big.id, "out")
    expected = ["exact-fhd.jpg", "exact-uhd.jpg", "icon.jpg", "mid.jpg", "near-fhd.jpg"]
    assert names(conn, segment=Segment.IDEAL) == expected
    assert names(conn, segment=Segment.NEAR_MISS) == ["four-three.jpg"]  # pinned in → no longer a near miss
    assert "icon.jpg" in names(conn, segment=Segment.IDEAL, display_id=fhd)
    assert "big.jpg" not in names(conn, segment=Segment.IDEAL, every_display=True)
    assert "icon.jpg" not in names(
        conn, segment=Segment.IDEAL, exact=True
    )  # a pin is not a fact about pixels
    assert "icon.jpg" not in names(conn, segment=Segment.IDEAL, exact=False)

    ideal.rebuild(conn, 16)
    ideal.rebuild(conn, 0)
    ideal.rebuild(conn, 16, [icon.id, big.id])
    assert names(conn, segment=Segment.IDEAL) == expected

    ids, changed = db.save_display_snapshot(conn, _detect(PORTRAIT), 2000)
    assert changed and len(ids) == 1
    ideal.rebuild(conn, 16)
    assert names(conn, segment=Segment.IDEAL) == ["icon.jpg", "near-fhd.jpg", "portrait.jpg"]
    assert (ideal.get_pin(conn, icon.id), ideal.get_pin(conn, big.id)) == ("in", "out")

    set_displays(conn, FHD, UHD, now=3000)
    ideal.rebuild(conn, 16)
    assert names(conn, segment=Segment.IDEAL) == expected
    ideal.set_pin(conn, big.id, None)
    ideal.set_pin(conn, icon.id, None)
    ideal.set_pin(conn, near.id, None)
    assert names(conn, segment=Segment.IDEAL) == ["big.jpg", "exact-fhd.jpg", "exact-uhd.jpg", "mid.jpg"]


def test_pinned_in_image_still_leaves_when_excluded_or_missing(
    two_screens: tuple[sqlite3.Connection, int, int],
) -> None:
    conn, _fhd, _uhd = two_screens
    icon = queries.get_image(conn, "/p/icon.jpg")
    assert icon
    ideal.set_pin(conn, icon.id, "in")
    conn.execute("UPDATE image SET missing = 1 WHERE id = ?", (icon.id,))
    assert "icon.jpg" not in names(conn, segment=Segment.IDEAL)


def test_set_pin_validates(two_screens: tuple[sqlite3.Connection, int, int]) -> None:
    conn, _fhd, _uhd = two_screens
    with pytest.raises(ValueError):
        ideal.set_pin(conn, 1, "sideways")  # type: ignore[arg-type]
    with pytest.raises(db.CatalogueError):
        ideal.set_pin(conn, 424_242, "in")
    ideal.set_pin(conn, 424_242, None)  # clearing a pin that does not exist is fine
    assert ideal.get_pin(conn, 424_242) is None


def _detect(*displays: Display) -> DisplayDetection:
    return detection(*displays)


# ── display changes: stored dimensions only, fast, and no file is opened ─────────────────────────────────


def test_stale_rows_of_a_disconnected_display_are_inert_even_before_the_rebuild(
    two_screens: tuple[sqlite3.Connection, int, int],
) -> None:
    conn, fhd, _uhd = two_screens
    _ids, changed = db.save_display_snapshot(conn, _detect(UHD), 2000)
    assert changed
    assert names(conn, segment=Segment.IDEAL) == ["big.jpg", "exact-uhd.jpg"]  # FHD rows no longer count
    assert names(conn, segment=Segment.IDEAL, display_id=fhd) == []
    ideal.rebuild(conn, 16)
    assert conn.execute("SELECT count(*) FROM ideal_image WHERE display_id = ?", (fhd,)).fetchone()[0] == 0


def test_no_display_means_an_empty_segment_not_an_error(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    add_image(conn, "/p/a.jpg", 3840, 2160)
    assert ideal.rebuild(conn, 16) == 0
    assert names(conn, segment=Segment.IDEAL) == []
    assert names(conn, segment=Segment.IDEAL, every_display=True) == []
    assert queries.segment_counts(conn)["every"] == 0


def test_rebuild_of_20k_rows_is_fast_and_opens_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rng = random.Random(SEED + 2)
    conn = open_db(tmp_path)
    set_displays(conn, FHD)
    sizes = [
        (1920, 1080),
        (3840, 2160),
        (2560, 1600),
        (3000, 2000),
        (1600, 1200),
        (1080, 1920),
        (800, 600),
        (5120, 2880),
    ]
    with db.transaction(conn):
        for n in range(20_000):
            w, h = rng.choice(sizes)
            add_image(conn, f"/photos/{n % 97}/img-{n}.jpg", w + rng.randint(0, 3), h + rng.randint(0, 3))
    ideal.rebuild(conn, 16)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a display change must not open any file")

    from PIL import Image

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(io, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Image, "open", forbidden)

    started = time.perf_counter()
    _ids, changed = db.save_display_snapshot(conn, _detect(FHD, UHD), 5000)
    written = ideal.rebuild(conn, 16)
    elapsed = time.perf_counter() - started
    monkeypatch.undo()

    assert changed and written > 10_000
    with capsys.disabled():
        print(
            f"\n[perf] ideal.rebuild: 20,000 images × 2 displays → {written} rows "
            f"in {elapsed * 1000:.1f} ms (budget 200 ms)"
        )
    assert elapsed < 1.0  # contract budget is 200 ms; the assertion is generous for slow CI machines

    started = time.perf_counter()
    page = queries.fetch_page(conn, QuerySpec(segment=Segment.IDEAL, limit=200))
    counts = queries.segment_counts(conn)
    query_elapsed = time.perf_counter() - started
    with capsys.disabled():
        print(f"[perf] ideal page + 8 segment counts over 20,000 rows: {query_elapsed * 1000:.1f} ms")
    assert page.total == counts["ideal"] > 0
    assert query_elapsed < 1.5
