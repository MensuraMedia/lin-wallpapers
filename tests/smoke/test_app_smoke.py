from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any

import pytest

from src.config.config_layout import Layout
from src.config.config_theme import Fonts
from src.pages import ALL_PAGES, SIDEBAR_PAGES
from src.ui.sidebar import FOOTER_NOTE, FOOTER_TITLE, NAV_ITEMS
from tests.conftest import PROJECT_ROOT
from tests.smoke.conftest import require_display

# tests/smoke/conftest.py skips (or, under `make smoke`, fails) these without a display
pytestmark = pytest.mark.smoke

NOISE = ("Gtk-WARNING", "Gtk-CRITICAL", "GLib-GObject-CRITICAL", "GLib-CRITICAL", "Gdk-CRITICAL", "Traceback")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "G_DEBUG": "fatal-criticals", "NO_AT_BRIDGE": "1"}
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_app_starts_switches_every_route_and_exits_cleanly() -> None:
    result = _run("-m", "tests.smoke.drive_app")
    assert result.returncode == 0, result.stderr
    assert "visited 9 routes" in result.stdout
    for marker in NOISE:
        assert marker not in result.stderr, result.stderr


# ── The P1 shell, measured in the running app (drive_app.py prints one FACTS line) ──────────────

NBSP = "\u00a0"
SIDEBAR_ROUTES = [route for _label, route, _icon in NAV_ITEMS]


@pytest.fixture(scope="module")
def facts() -> dict[str, Any]:
    require_display()  # module-scoped, so it is set up before the per-test display check
    result = _run("-m", "tests.smoke.drive_app")
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("FACTS "))
    return dict(json.loads(line.removeprefix("FACTS ")))


def _plain(text: str) -> str:
    return text.replace(NBSP, " ")


def test_every_label_renders_in_the_ui_font(facts: dict[str, Any]) -> None:
    family = Fonts.FAMILY.split(",")[0].strip()
    if family not in facts["installed_families"]:
        pytest.skip(f"the {family!r} font is not installed here, so Pango falls back down the stack")
    assert facts["label_families"] == [family]


def test_sidebar_geometry_matches_the_layout_constants(facts: dict[str, Any]) -> None:
    dims = Layout.dimensions
    assert facts["sidebar_width"] == dims.SIDEBAR_WIDTH == 150
    assert list(facts["nav"]) == SIDEBAR_ROUTES
    for route, button in facts["nav"].items():
        assert button["height"] == dims.NAV_BUTTON_HEIGHT == 28, route
        assert button["icon"] == [dims.NAV_ICON_SIZE, dims.NAV_ICON_SIZE], route


def test_nav_buttons_are_labelled_with_their_route(facts: dict[str, Any]) -> None:
    titles = {page.route: page.title for page in SIDEBAR_PAGES}
    for label, route, _icon in NAV_ITEMS:
        shown = _plain(facts["nav"][route]["label"])
        assert shown == label, route
        assert shown == titles[route], f"the {route!r} button does not name the page it opens"


def test_exactly_the_current_route_is_highlighted_in_accent(facts: dict[str, Any]) -> None:
    accent = [round(channel * 255) for channel in facts["tokens"]["accent"][:3]]
    assert set(facts["per_route"]) == {page.route for page in ALL_PAGES}
    for route, state in facts["per_route"].items():
        expected = [route] if route in SIDEBAR_ROUTES else []  # About is reached from Settings: no highlight
        assert state["active"] == expected, route
        for button, color in state["glyph_color"].items():
            if button == route:
                assert color == accent, f"the active {button!r} glyph is not drawn in the accent token"
            else:
                assert color != accent, f"the inactive {button!r} glyph is accent on {route!r}"


def test_footer_states_no_machine_fact(facts: dict[str, Any]) -> None:
    """Until the M3 probes exist the panel may only say so (no fake data in src/)."""
    assert [_plain(text) for text in facts["footer"]] == [FOOTER_TITLE, FOOTER_NOTE]
    assert (FOOTER_TITLE, FOOTER_NOTE) == ("THIS MACHINE", "Detected in M3")
    assert not re.search(r"\d+\.\d+", " ".join(facts["footer"])), "a version number is a machine fact"


def test_every_page_is_headed_by_its_title(facts: dict[str, Any]) -> None:
    for page in ALL_PAGES:
        assert page.title, page.route
        assert facts["page_titles"][page.route] == [page.title], page.route


def test_accessible_names_are_plain_text(facts: dict[str, Any]) -> None:
    """compat.tracked() puts U+00A0 into the rendered text only; a screen reader gets ordinary spaces."""
    assert any(NBSP in text for text, _name in facts["accessible"]), "no tracked label left: drop this test"
    for text, name in facts["accessible"]:
        assert NBSP not in (name or ""), repr(name)
        assert name == _plain(text), repr(text)


def test_sidebar_hairline_sits_on_the_sidebar_surface(facts: dict[str, Any]) -> None:
    pixels = facts["hairline"]
    if pixels is None:
        pytest.skip("the display gave no window contents to read back")
    tokens = facts["tokens"]
    red, green, blue, alpha = tokens["stroke"]
    surface, base = tokens["bg-surface"], tokens["bg-base"]
    stroke_on_surface = [
        round(255 * (tone * alpha + under * (1 - alpha)))
        for tone, under in zip((red, green, blue), surface, strict=False)
    ]
    assert pixels["inside"] == [round(255 * channel) for channel in surface[:3]]
    assert pixels["outside"] == [round(255 * channel) for channel in base[:3]]
    for got, want in zip(pixels["edge"], stroke_on_surface, strict=True):
        assert abs(got - want) <= 1, f"hairline {pixels['edge']} != stroke on surface {stroke_on_surface}"


def test_logo_block_is_centred_in_the_sidebar(facts: dict[str, Any]) -> None:
    """User-requested deviation from docs/mockups (left-aligned there): tile, name and tagline are one
    centred unit; the nav rows and the "this machine" panel stay left-aligned."""
    logo = facts["logo"]
    centre = facts["sidebar_width"] / 2
    assert logo["tile_size"] == [Layout.dimensions.LOGO_SIZE, Layout.dimensions.LOGO_SIZE]
    assert abs(logo["tile_centre"] - centre) <= 1, logo
    for key in ("logo-name", "logo-tagline"):
        assert logo[key]["xalign"] == 0.5, key
        assert abs(logo[key]["centre"] - centre) <= 1.5, (key, logo[key])
    assert logo["nav_label_xalign"] == 0
    assert logo["footer_xalign"] == [0, 0]


def test_logo_glyph_is_centred_in_its_tile(facts: dict[str, Any]) -> None:
    margins = facts["logo"].get("glyph_margins")
    if margins is None:
        pytest.skip("the display gave no window contents to read back")
    left, right, top, bottom = margins
    assert abs(left - right) <= 1, margins
    assert abs(top - bottom) <= 1, margins
    assert min(margins) >= 8, f"the glyph should sit well inside the tile: {margins}"


def test_nothing_is_left_running() -> None:
    """The app is a window, not a service: when it exits, its whole session is empty."""
    env = {**os.environ, "NO_AT_BRIDGE": "1"}
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.smoke.drive_app"],
        cwd=PROJECT_ROOT, env=env, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    assert app.wait(timeout=60) == 0
    survivors = subprocess.run(["pgrep", "-s", str(app.pid)], capture_output=True, text=True, check=False)
    assert survivors.stdout.strip() == ""


def test_gtk4_gate() -> None:
    """LWP_GTK=4.0 selects GTK 4 through the single gate (M0 acceptance 6) — where GTK 4 is installed."""
    probe = "import gi; gi.require_version('Gtk', '4.0')"
    if subprocess.run([sys.executable, "-c", probe], capture_output=True, check=False).returncode != 0:
        pytest.skip("GTK 4 typelib not installed")
    code = "import src.gtk_version as g; assert g.IS_GTK4 and g.Gtk.get_major_version() == 4"
    env = {**os.environ, "LWP_GTK": "4.0"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
