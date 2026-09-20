"""Pure parsers of ``scanner/displays.py``: ``xrandr --current`` text, declared displays, the record."""

from __future__ import annotations

import pytest

from src.scanner.displays import Display, DisplaySource, DisplaySpecError, parse_declared, parse_xrandr

AXES = "(normal left inverted right x axis y axis)"

LAPTOP = f"""\
Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 {AXES} 344mm x 194mm
   1920x1080     60.01*+  59.97    59.96    59.93    48.00
   1680x1050     59.95    59.88
   1280x720      60.00    59.99    59.86    59.74
HDMI-1 disconnected {AXES}
DP-1 disconnected {AXES}
"""

LAPTOP_EXTERNAL = f"""\
Screen 0: minimum 320 x 200, current 4480 x 1440, maximum 16384 x 16384
eDP-1 connected 1920x1080+2560+360 {AXES} 309mm x 174mm
   1920x1080     60.02*+  48.01
HDMI-1 connected primary 2560x1440+0+0 {AXES} 597mm x 336mm
   2560x1440     59.95*+
   1920x1080     60.00    50.00    59.94
   1920x1080i    60.00    50.00    59.94
DP-1 disconnected {AXES}
"""

ULTRAWIDE_AMDGPU = f"""\
Screen 0: minimum 320 x 200, current 2560 x 1080, maximum 16384 x 16384
DisplayPort-0 disconnected {AXES}
HDMI-A-0 connected primary 2560x1080+0+0 {AXES} 798mm x 334mm
   2560x1080     59.98 +  74.99*   50.00
   3840x2160     30.00    25.00    24.00    29.97    23.98
   1920x1080     74.99    60.00    50.00    59.94
"""

ROTATED_LEFT = f"""\
Screen 0: minimum 8 x 8, current 3000 x 1920, maximum 32767 x 32767
DP-2 connected primary 1920x1080+0+420 {AXES} 527mm x 296mm
   1920x1080     60.00*+  50.00    59.94
HDMI-0 connected 1080x1920+1920+0 left {AXES} 527mm x 296mm
   1920x1080     60.00*+  50.00    59.94
   1280x720      60.00    50.00
DVI-D-0 connected 1200x1600+3000+0 right X axis {AXES} 408mm x 306mm
   1600x1200     60.00*+
DP-3 connected 1280x1024+4200+0 inverted {AXES} 376mm x 301mm
   1280x1024     60.02*+
"""

CONNECTED_BUT_OFF = f"""\
Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 {AXES} 344mm x 194mm
   1920x1080     60.01*+
HDMI-1 connected {AXES} 597mm x 336mm
   2560x1440     59.95 +
   1920x1080     60.00
"""

HIDPI = f"""\
Screen 0: minimum 320 x 200, current 3840 x 2400, maximum 16384 x 16384
eDP-1 connected primary 3840x2400+0+0 {AXES} 288mm x 180mm
   3840x2400     60.00*+  48.00
   1920x1200     59.95
"""

SCALED_FRAMEBUFFER = f"""\
Screen 0: minimum 320 x 200, current 3840 x 2160, maximum 16384 x 16384
eDP-1 connected primary 3840x2160+0+0 {AXES} 344mm x 194mm
   1920x1080     60.01*+  59.97
"""

SCALED_AND_ROTATED = f"""\
Screen 0: minimum 320 x 200, current 2160 x 3840, maximum 16384 x 16384
DP-1 connected 2160x3840+0+0 left {AXES} 527mm x 296mm
   1920x1080     60.00*+
"""

NEGATIVE_OFFSET_AND_DUPLICATE = f"""\
DP-1 connected 1920x1080+-1920+0 {AXES} 0mm x 0mm
   1920x1080     60.00*
DP-1 connected 1280x720+0+0 {AXES} 0mm x 0mm
   1280x720      60.00*
"""


def sizes(text: str) -> list[tuple[str, int, int, bool]]:
    return [(d.name, d.width, d.height, d.primary) for d in parse_xrandr(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (LAPTOP, [("eDP-1", 1920, 1080, True)]),
        (LAPTOP_EXTERNAL, [("eDP-1", 1920, 1080, False), ("HDMI-1", 2560, 1440, True)]),
        (ULTRAWIDE_AMDGPU, [("HDMI-A-0", 2560, 1080, True)]),
        (
            ROTATED_LEFT,
            [
                ("DP-2", 1920, 1080, True),
                ("HDMI-0", 1080, 1920, False),
                ("DVI-D-0", 1200, 1600, False),
                ("DP-3", 1280, 1024, False),
            ],
        ),
        (CONNECTED_BUT_OFF, [("eDP-1", 1920, 1080, True)]),
        (HIDPI, [("eDP-1", 3840, 2400, True)]),
        (SCALED_FRAMEBUFFER, [("eDP-1", 1920, 1080, True)]),
        (SCALED_AND_ROTATED, [("DP-1", 1080, 1920, False)]),
        (NEGATIVE_OFFSET_AND_DUPLICATE, [("DP-1", 1920, 1080, False)]),
        ("", []),
        ("Can't open display :0\n", []),
        ("\x00\x01\x02 connected 99x\n   *\n\tconnected\n", []),
        ("   1920x1080     60.00*+\n", []),  # a mode line that belongs to no output
        (f"DP-1 connected 0x0+0+0 {AXES}\n", []),
        (f"DP-1 connected 999999x999999+0+0 {AXES}\n", []),
        (f"DP-1 unknown connection 1920x1080+0+0 {AXES}\n", []),
    ],
)
def test_parse_xrandr(text: str, expected: list[tuple[str, int, int, bool]]) -> None:
    assert sizes(text) == expected


def test_parse_xrandr_record_fields() -> None:
    (display,) = parse_xrandr(HIDPI)
    assert display == Display("eDP-1", 3840, 2400, 1.0, True, DisplaySource.XRANDR)


def test_parse_xrandr_mode_lines_of_an_off_output_do_not_leak_into_the_next() -> None:
    text = f"HDMI-1 connected {AXES}\n   2560x1440     59.95*\neDP-1 connected 1920x1080+0+0 {AXES}\n"
    assert sizes(text) == [("eDP-1", 1920, 1080, False)]


# ------------------------------------------------------------------------------------------------ declared


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3840x2160", [("declared-1", 3840, 2160)]),
        ("3840x2160,1920x1080", [("declared-1", 3840, 2160), ("declared-2", 1920, 1080)]),
        ("1920×1080", [("declared-1", 1920, 1080)]),
        ("1920X1080", [("declared-1", 1920, 1080)]),
        ("  2560x1440 ,\t1080x1920 ", [("declared-1", 2560, 1440), ("declared-2", 1080, 1920)]),
        ("1920x1080,1920×1080,1280x720", [("declared-1", 1920, 1080), ("declared-2", 1280, 720)]),
        ("320x320,16384x16384", [("declared-1", 320, 320), ("declared-2", 16384, 16384)]),
    ],
)
def test_parse_declared_ok(text: str, expected: list[tuple[str, int, int]]) -> None:
    displays = parse_declared(text)
    assert [(d.name, d.width, d.height) for d in displays] == expected
    assert all(d.source is DisplaySource.DECLARED and d.scale == 1.0 and not d.primary for d in displays)


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "0x0",
        "000x000",
        "319x1080",
        "1920x319",
        "16385x1080",
        "99999x1",
        "99999x99999",
        "-1920x1080",
        "1920x-1080",
        "1920",
        "1920x",
        "x1080",
        "1920x1080x3",
        "1920 x 1080",
        "1920x1080,",
        ",1920x1080",
        "1920x1080;1280x720",
        "fullhd",
        "1920x1080@60",
        "1e3x1080",
        "１９２０x1080",
        "1920x1080\n1280x720",
        ",".join(f"{1000 + n}x1000" for n in range(9)),
    ],
)
def test_parse_declared_rejects(text: str) -> None:
    with pytest.raises(DisplaySpecError) as caught:
        parse_declared(text)
    assert isinstance(caught.value, ValueError)
    assert caught.value.problem
    assert "\n" not in str(caught.value)


def test_parse_declared_eight_is_the_limit_and_duplicates_do_not_count() -> None:
    eight = ",".join(f"{1000 + n}x1000" for n in range(8))
    assert len(parse_declared(eight)) == 8
    assert len(parse_declared(eight + ",1000x1000")) == 8


def test_display_spec_error_names_the_offending_part() -> None:
    with pytest.raises(DisplaySpecError) as caught:
        parse_declared("1920x1080,nonsense")
    assert caught.value.spec == "nonsense"


# -------------------------------------------------------------------------------------------------- record


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "", "width": 1920, "height": 1080},
        {"name": "x", "width": 0, "height": 1080},
        {"name": "x", "width": 1920, "height": -1},
        {"name": "x", "width": 1920, "height": 1080, "scale": 0.0},
        {"name": "x", "width": 1920, "height": 1080, "scale": float("nan")},
    ],
)
def test_display_validates(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Display(**kwargs)  # type: ignore[arg-type]


def test_display_is_frozen_and_hashable() -> None:
    display = Display("eDP-1", 1920, 1080)
    assert display.source is DisplaySource.DECLARED
    assert {display: 1}[Display("eDP-1", 1920, 1080)] == 1
    with pytest.raises(AttributeError):
        display.width = 1  # type: ignore[misc]
