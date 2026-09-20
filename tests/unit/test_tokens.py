from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.config import TOKEN_NAMES, load_tokens
from src.config.config_theme import STYLE_FILE, TOKENS_FILE, Fonts
from tests.conftest import PROJECT_ROOT

HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
COLOR_FUNCTION = re.compile(r"\brgba?\(|\bhsla?\(")

# Every CSS named color (CSS Color 4). `transparent`, `inherit` and `currentColor` carry no color
# of their own and stay allowed.
NAMED_COLORS = frozenset(
    # a word list reads better than 148 quoted strings
    """aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown
    burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan
    darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid
    darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet
    deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro
    ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki
    lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow
    lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray
    lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine
    mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise
    mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab
    orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru
    pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown
    seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan
    teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen""".split()  # noqa: SIM905
)
_DECLARATION = re.compile(r"([\w-]+)\s*:\s*([^;{}]+)[;}]")
_WORD = re.compile(r"(?<![\w@.#-])[A-Za-z]+(?![\w(-])")
_QUOTED = re.compile(r"""(["']).*?\1""")

PY_HEX = re.compile(r"""["']#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})["']""")
# call name → index of its first color argument (a gradient stop starts with its offset)
CAIRO_COLOR_CALLS = {
    "set_source_rgb": 0,
    "set_source_rgba": 0,
    "add_color_stop_rgb": 1,
    "add_color_stop_rgba": 1,
}


def css_color_problems(css: str) -> list[str]:
    """Every literal color in a component stylesheet: hex, rgb()/hsl(), named colors, -gtk-gradient."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    problems = [f"hex color {match.group(0)}" for match in HEX.finditer(css)]
    problems += [f"color function {match.group(0)}…)" for match in COLOR_FUNCTION.finditer(css)]
    if "-gtk-gradient" in css:
        problems.append("-gtk-gradient")
    for prop, value in _DECLARATION.findall(css):
        if prop == "font-family":
            continue
        for word in _WORD.findall(_QUOTED.sub("", value)):
            if word.lower() in NAMED_COLORS:
                problems.append(f"named color {word!r} in {prop}")
    return problems


def _is_number(node: ast.expr) -> bool:
    if isinstance(node, ast.UnaryOp):
        node = node.operand
    if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
        return False
    return isinstance(node.value, int | float)


def python_color_problems(source: str) -> list[str]:
    """Literal colors in Python: hex strings, numeric Cairo sources / gradient stops, ``Gdk.RGBA(…)``."""
    problems = [f"hex string {match.group(0)}" for match in PY_HEX.finditer(source)]
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name == "RGBA":
            problems.append(f"line {node.lineno}: RGBA(…) built in code — use compat.lookup_color()")
        elif name in CAIRO_COLOR_CALLS:
            values = [*node.args[CAIRO_COLOR_CALLS[name] :], *(keyword.value for keyword in node.keywords)]
            if any(_is_number(value) for value in values):
                problems.append(f"line {node.lineno}: {name}() with a numeric color — use lookup_color()")
    return problems


EXPECTED = {
    "bg-base": "#1E2233",
    "bg-surface": "#252A3E",
    "bg-raised": "#2B3044",
    "text": "#F2F3F7",
    "text-dim": "#8A8E9E",
    "accent": "#FFC700",
    "accent-2": "#FFB500",
    "on-accent": "#1A1400",
    "ok": "#4ADE80",
    "warn": "#FFB500",
    "danger": "#EF4444",
}


def test_tokens_match_the_design_language() -> None:
    tokens = load_tokens()
    assert set(tokens) == set(TOKEN_NAMES)
    for name, value in EXPECTED.items():
        assert tokens[name].upper() == value.upper(), name
    assert tokens["stroke"].replace(" ", "") == "rgba(255,255,255,0.08)"


def test_style_css_uses_tokens_only() -> None:
    css = re.sub(r"/\*.*?\*/", "", STYLE_FILE.read_text(), flags=re.S)
    assert not HEX.search(css), "hex color outside tokens.css"
    assert not COLOR_FUNCTION.search(css), "literal color outside tokens.css"
    assert "-gtk-gradient" not in css
    assert css_color_problems(css) == []
    used = set(re.findall(r"@([a-z][\w-]*)", css))
    assert used <= set(TOKEN_NAMES), f"unknown tokens: {used - set(TOKEN_NAMES)}"


def test_no_hex_colors_in_python() -> None:
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)}: {match.group(0)}"
        for path in (PROJECT_ROOT / "src").rglob("*.py")
        for match in re.finditer(r"""["']#[0-9A-Fa-f]{6}["']""", path.read_text())
    ]
    assert not offenders, offenders


def test_no_literal_colors_in_python() -> None:
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)}: {problem}"
        for path in sorted((PROJECT_ROOT / "src").rglob("*.py"))
        for problem in python_color_problems(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    "declaration",
    [
        "color: black;",
        "background-color: White;",
        "border: 1px solid gray;",
        "box-shadow: 0 1px 2px red",  # last declaration of a block, no semicolon
        "background-image: linear-gradient(to bottom, gold, @accent);",
        "color: #fff;",
        "color: #FFC70080;",
        "color: rgb(0, 0, 0);",
        "color: hsla(0, 0%, 0%, 0.5);",
        "background-image: -gtk-gradient(linear, left top, left bottom, from(@accent), to(@accent-2));",
    ],
)
def test_literal_css_colors_are_rejected(declaration: str) -> None:
    assert css_color_problems(f".card {{ {declaration} }}"), declaration


def test_token_css_is_accepted() -> None:
    css = """
    /* black and white are only words in this comment */
    .snow-card, .red { color: @text; background-color: alpha(@accent, 0.14); border: 1px solid @stroke; }
    .nav-button { color: inherit; background-color: transparent; border-color: currentColor; }
    * { font-family: "Tan Sans", sans-serif; }
    .pill { background-image: linear-gradient(to bottom, @accent, @accent-2); }
    .nav-button { color: mix(@text, @text-dim, 0.4); }
    """
    assert css_color_problems(css) == []


@pytest.mark.parametrize(
    "source",
    [
        'COLOR = "#fff"',
        'COLOR = "#FFFA"',
        'COLOR = "#FFC700"',
        "COLOR = '#FFC70080'",
        "cr.set_source_rgb(1, 0.5, 0)",
        "cr.set_source_rgba(r, g, b, 0.5)",
        "cr.set_source_rgba(-1.0, g, b, a)",
        "gradient.add_color_stop_rgb(0, 1.0, 1.0, 1.0)",
        "gradient.add_color_stop_rgba(0.5, *rgb, 0.2)",
        "color = Gdk.RGBA(1, 0, 0, 1)",
        "color = Gdk.RGBA()",
        "color = RGBA(red=1.0)",
    ],
)
def test_literal_python_colors_are_rejected(source: str) -> None:
    assert python_color_problems(source), source


def test_token_driven_python_is_accepted(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text(
        'cr.set_source_rgba(*compat.lookup_color(self, "accent"))\n'
        'gradient.add_color_stop_rgba(0, *compat.lookup_color(self, "accent"))\n'
        "gradient.add_color_stop_rgba(1, red, green, blue, alpha)\n"
        'ISSUE = "#12"\n'
        'ANCHOR = "#heading"\n'
    )
    assert python_color_problems(good.read_text()) == []


def test_fonts_match_the_design_language() -> None:
    """The Ubuntu family everywhere (TECHNICAL-CONCEPT §16); config_theme.Fonts is the only source."""
    assert Fonts.FAMILY.split(",")[0].strip() == "Ubuntu"
    assert Fonts.FAMILY_MONO.split(",")[0].strip() == "Ubuntu Mono"
    assert Fonts.FAMILY.split(",")[-1].strip() == "sans-serif"
    assert Fonts.FAMILY_MONO.split(",")[-1].strip() == "monospace"


def test_font_css_is_generated_from_fonts_and_nowhere_else() -> None:
    assert Fonts.css() == (
        "* { font-family: Ubuntu, Cantarell, sans-serif; }\n"
        '.mono { font-family: "Ubuntu Mono", "DejaVu Sans Mono", monospace; }\n'
    )
    for sheet in (STYLE_FILE, TOKENS_FILE):
        css = re.sub(r"/\*.*?\*/", "", sheet.read_text(), flags=re.S)
        assert "font-family" not in css, f"{sheet.name}: font stacks come from config_theme.Fonts"
        assert not re.search(r"\bfont\s*:", css), f"{sheet.name}: the font shorthand would override Fonts"


def test_token_file_is_the_default_path() -> None:
    assert TOKENS_FILE.name == "tokens.css"
