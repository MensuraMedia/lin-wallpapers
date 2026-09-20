"""compat helpers against real GTK 3 widgets (needs a display to instantiate them)."""

from __future__ import annotations

import pytest

# tests/smoke/conftest.py skips (or, under `make smoke`, fails) these without a display
pytestmark = pytest.mark.smoke


def test_append_and_set_child() -> None:
    from src.gtk_version import Gtk
    from src.ui import compat

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    first, second = Gtk.Label(label="a"), Gtk.Label(label="b")
    compat.append(box, first)
    compat.append(box, second, expand=True)
    assert box.get_children() == [first, second]
    assert box.query_child_packing(second)[0] is True

    scrolled = Gtk.ScrolledWindow()
    compat.set_child(scrolled, box)
    assert box.get_parent() is not None


def test_css_classes_and_wrap() -> None:
    from src.gtk_version import Gtk
    from src.ui import compat

    label = Gtk.Label(label="x")
    compat.add_class(label, "chip", "accent")
    assert label.get_style_context().has_class("accent")
    compat.remove_class(label, "accent")
    assert not label.get_style_context().has_class("accent")
    compat.set_wrap(label)
    assert label.get_line_wrap()


def test_canvas_area_requires_on_draw_and_tokens_resolve() -> None:
    from src.config.config_themes import DEFAULT_THEME, get_theme
    from src.modules.manager_theme_applicator import ThemeApplicator
    from src.ui import compat

    ThemeApplicator().apply_theme(get_theme(DEFAULT_THEME))
    canvas = compat.CanvasArea(10, 10)
    with pytest.raises(NotImplementedError):
        canvas.on_draw(None, 10, 10)
    red, green, blue, alpha = compat.lookup_color(canvas, "accent")
    assert (round(red * 255), round(green * 255), round(blue * 255), alpha) == (255, 199, 0, 1.0)
    with pytest.raises(KeyError):
        compat.lookup_color(canvas, "not-a-token")


def test_applicator_loads_the_generated_font_rules_and_fresh_css() -> None:
    from src.config.config_theme import STYLE_FILE, TOKENS_FILE, Fonts
    from src.config.config_themes import DEFAULT_THEME, get_theme
    from src.modules.manager_theme_applicator import ThemeApplicator

    css = ThemeApplicator().build_css(get_theme(DEFAULT_THEME))
    assert Fonts.css() in css
    assert css.index(Fonts.css()) < css.index(".sidebar")  # ahead of the component sheet
    # Whatever it was read from (a fresh bundle or resources/), it is the CSS as it is on disk now.
    assert TOKENS_FILE.read_text(encoding="utf-8") in css
    assert STYLE_FILE.read_text(encoding="utf-8") in css
