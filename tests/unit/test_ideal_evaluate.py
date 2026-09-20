"""``ideal.evaluate`` / ``ideal.explain``: the pure dimension tests of concept §6.1 (rulings Q1–Q3)."""

from __future__ import annotations

import ast
import inspect

import pytest

from src.catalogue import ideal
from src.catalogue.ideal import ImageDims, Verdict
from src.scanner.displays import Display

FHD = Display("eDP-1", 1920, 1080)
ROTATED = Display("DP-2", 1080, 1920)
T = ideal.Test


def verdict(
    w: int, h: int, display: Display = FHD, threshold: int = ideal.DEFAULT_THRESHOLD_PCT, **flags: bool
):
    return ideal.evaluate(ImageDims(w, h, **flags), display, threshold)


def test_constants_follow_the_rulings() -> None:
    assert ideal.DEFAULT_THRESHOLD_PCT == 16  # Q1
    assert (ideal.MAX_THRESHOLD_PCT, ideal.NEAR_CROP_PCT, ideal.NEAR_COVER_PCT) == (40, 25, 90)  # Q2


def test_exact_match() -> None:
    v = verdict(1920, 1080)
    assert (v.verdict, v.exact, v.crop_loss, v.coverage, v.failed) == (Verdict.IDEAL, True, 0.0, 1.0, ())


def test_larger_than_needed() -> None:
    v = verdict(3840, 2160)
    assert v.verdict is Verdict.IDEAL and not v.exact and v.crop_loss == 0.0 and v.coverage == 1.0


@pytest.mark.parametrize(("w", "h"), [(1919, 1080), (1920, 1079), (1919, 1079)])
def test_one_pixel_short_is_a_near_miss_not_ideal(w: int, h: int) -> None:
    v = verdict(w, h)
    assert v.verdict is Verdict.NEAR
    assert T.COVERS in v.failed and T.ORIENTATION not in v.failed and T.INTEGRITY not in v.failed


def test_16_10_on_16_9_loses_ten_percent_and_passes() -> None:
    v = verdict(2560, 1600)
    assert v.verdict is Verdict.IDEAL
    assert v.crop_loss == pytest.approx(0.10)
    assert verdict(2560, 1600, threshold=10).verdict is Verdict.IDEAL  # exactly at the threshold: passes
    assert verdict(2560, 1600, threshold=9).verdict is Verdict.NEAR


def test_3_2_on_16_9_passes_at_16_and_fails_at_15() -> None:
    v = verdict(3000, 2000)
    assert v.crop_loss == pytest.approx(0.15625)
    assert v.verdict is Verdict.IDEAL  # ruling Q1: the default is 16 %
    at_15 = verdict(3000, 2000, threshold=15)
    assert at_15.verdict is Verdict.NEAR and at_15.failed == (T.CROP,)


def test_4_3_is_a_near_miss_exactly_at_the_25_percent_boundary() -> None:
    v = verdict(2880, 2160)
    assert v.crop_loss == pytest.approx(0.25)
    assert v.verdict is Verdict.NEAR and v.failed == (T.CROP,)
    assert verdict(2880, 2160, threshold=25).verdict is Verdict.IDEAL  # equality passes CROP(25)
    assert verdict(2880, 2161).verdict is Verdict.NO  # a hair beyond 25 %: not even near


def test_square_is_not_ideal_nor_near() -> None:
    v = verdict(4000, 4000)
    assert v.verdict is Verdict.NO and v.failed == (T.CROP,)  # square matches either orientation
    assert v.crop_loss == pytest.approx(1 - 1080 / 1920)


def test_portrait_on_landscape_fails_orientation() -> None:
    v = verdict(2160, 3840)
    assert v.verdict is Verdict.NO and T.ORIENTATION in v.failed


def test_portrait_on_a_rotated_display_is_ideal() -> None:
    v = verdict(2160, 3840, ROTATED)
    assert v.verdict is Verdict.IDEAL and v.crop_loss == 0.0
    assert verdict(1080, 1920, ROTATED).exact
    assert T.ORIENTATION in verdict(3840, 2160, ROTATED).failed


def test_exif_rotated_dimensions_are_what_is_judged() -> None:
    # A 1080 × 1920 sensor frame with EXIF orientation 6 is stored as 1920 × 1080 (after rotation).
    assert verdict(1920, 1080).verdict is Verdict.IDEAL
    assert verdict(1080, 1920).verdict is Verdict.NO


@pytest.mark.parametrize("flags", [{"has_alpha": True}, {"is_animated": True}, {"decodable": False}])
def test_alpha_animated_undecodable_are_never_ideal_or_near(flags: dict[str, bool]) -> None:
    v = verdict(3840, 2160, **flags)
    assert v.verdict is Verdict.NO and v.failed == (T.INTEGRITY,)


@pytest.mark.parametrize(("w", "h"), [(0, 0), (0, 1080), (1920, 0), (-1920, -1080), (-1, 5), (10**7, 10**7)])
def test_zero_negative_and_absurd_dimensions_are_rejected_as_data(w: int, h: int) -> None:
    v = verdict(w, h)
    assert v.verdict is Verdict.NO and v.failed == (T.INTEGRITY,) and not v.exact


def test_non_integer_dimensions_are_rejected() -> None:
    v = ideal.evaluate(ImageDims(1920.0, 1080.0), FHD)  # type: ignore[arg-type]
    assert v.verdict is Verdict.NO
    assert ideal.evaluate(ImageDims(None, None), FHD).verdict is Verdict.NO  # type: ignore[arg-type]


def test_threshold_zero_admits_only_a_lossless_crop() -> None:
    assert verdict(3840, 2160, threshold=0).verdict is Verdict.IDEAL
    assert verdict(3841, 2160, threshold=0).verdict is Verdict.NEAR
    assert verdict(3841, 2160, threshold=0).failed == (T.CROP,)


def test_threshold_forty() -> None:
    assert verdict(2880, 2160, threshold=40).verdict is Verdict.IDEAL  # 4:3, 25 %
    v = verdict(4001, 4000, threshold=40)  # barely landscape: loses ≈ 43.7 %
    assert v.verdict is Verdict.NO and v.failed == (T.CROP,)


@pytest.mark.parametrize("bad", [-1, 41, 100, 15.0, "16", None, True])
def test_threshold_out_of_range_is_a_value_error(bad: object) -> None:
    with pytest.raises(ValueError):
        ideal.evaluate(ImageDims(1920, 1080), FHD, bad)  # type: ignore[arg-type]


def test_near_miss_needs_90_percent_linear_coverage_on_both_axes() -> None:
    assert verdict(1760, 990).verdict is Verdict.NEAR  # the concept's example: 91.7 %
    assert verdict(1728, 972).verdict is Verdict.NEAR  # exactly 90 %
    assert verdict(1727, 972).verdict is Verdict.NO
    assert verdict(1728, 971).verdict is Verdict.NO
    assert verdict(1600, 900).verdict is Verdict.NO  # ruling Q2: 83 % is a plain "no"
    assert verdict(64, 36).verdict is Verdict.NO  # a perfectly 16:9 icon is not a near miss


def test_near_miss_can_name_both_tests() -> None:
    v = verdict(1800, 1350)  # 4:3, slightly too narrow
    assert v.verdict is Verdict.NEAR and v.failed == (T.COVERS, T.CROP)


def test_no_floats_take_part_in_a_decision_at_huge_sizes() -> None:
    # 2^53-scale products: float arithmetic would round these two apart/together; integers do not.
    w, h = 999_999, 562_500  # w·H vs W·h differ by a whisker around the 0 % threshold
    a, b = w * 1080, 1920 * h
    expected = Verdict.IDEAL if 100 * min(a, b) >= 100 * max(a, b) else Verdict.NEAR
    assert verdict(w, h, threshold=0).verdict is expected is Verdict.NEAR


def test_evaluate_source_has_no_float_in_a_comparison() -> None:
    tree = ast.parse(inspect.getsource(ideal.evaluate).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for sub in ast.walk(node):
                assert not (isinstance(sub, ast.Constant) and isinstance(sub.value, float))
                assert not (isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div))


def test_bad_display_is_a_programming_error() -> None:
    class Fake:
        name = "x"
        width = 0
        height = 1080

    with pytest.raises(ValueError):
        ideal.evaluate(ImageDims(1920, 1080), Fake())  # type: ignore[arg-type]


# ── explanations ─────────────────────────────────────────────────────────────────────────────────────────


def explain(w: int, h: int, display: Display = FHD, threshold: int = 16, **flags: bool) -> str:
    dims = ImageDims(w, h, **flags)
    return ideal.explain(dims, display, ideal.evaluate(dims, display, threshold))


def test_explain_member_matches_the_concept_wording() -> None:
    assert explain(3840, 2160) == "3840 × 2160 covers 1920 × 1080; fill crop loses 0 %"
    assert explain(3000, 2000) == "3000 × 2000 covers 1920 × 1080; fill crop loses 15.6 %"
    assert explain(1920, 1080) == "1920 × 1080 matches eDP-1 exactly"


def test_explain_near_miss_names_the_failed_test() -> None:
    assert explain(1760, 990) == "1760 × 990 — 8 % too small for eDP-1"
    assert explain(2880, 2160) == "2880 × 2160 — fill crop on eDP-1 loses 25 % of the picture"
    assert explain(1919, 1080) == "1919 × 1080 — 1 % too small for eDP-1"  # never "0 % too small"
    both = explain(1800, 1350)
    assert "too small for eDP-1" in both and "fill crop on eDP-1 loses 25 %" in both


def test_explain_non_members() -> None:
    assert explain(2160, 3840).startswith("2160 × 3840 — is portrait but eDP-1 is landscape")
    assert explain(3840, 2160, has_alpha=True) == "3840 × 2160 — has an alpha channel"
    assert explain(3840, 2160, is_animated=True) == "3840 × 2160 — is animated"
    assert explain(3840, 2160, decodable=False) == "3840 × 2160 — could not be decoded"
    assert explain(0, 0, decodable=False) == "dimensions unknown — the file could not be read"


def test_the_test_enum_is_not_collected_by_pytest() -> None:
    assert ideal.Test.__test__ is False
    assert [t.value for t in ideal.Test] == ["covers", "crop", "orientation", "integrity"]
