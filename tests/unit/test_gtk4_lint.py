from __future__ import annotations

import sys
from pathlib import Path

from tests.conftest import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "tools"))
import gtk4_lint

BAD = """
from gi.repository import Gtk
import gi
gi.require_version("Gtk", "3.0")
box.pack_start(child, True, True, 0)
window.add(box)
window.show_all()
menu = Gtk.Menu()
widget.connect("button-press-event", handler)
widget.override_background_color(0, None)
seen.add(1)  # gtk4-lint: ok (a set)
"""


def test_source_tree_is_clean() -> None:
    assert gtk4_lint.lint([PROJECT_ROOT / "src"]) == []


def test_banned_calls_are_caught(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text(BAD)
    problems = "\n".join(gtk4_lint.lint([bad]))
    for needle in (
        "pack_start",
        ".add()",
        "show_all",
        "Gtk.Menu",
        "button-press-event",
        "override_",
        "require_version",
        "single version gate",
    ):
        assert needle in problems, needle
    assert ":11:" not in problems  # the pragma line


# One GTK 3-only construct per line: every line must be reported, each for its own reason.
EVASIONS = (
    ("import gi.repository.Gtk as G", "single version gate"),
    ("import gi.repository.Gdk", "single version gate"),
    ("from gi import repository", "single version gate"),
    ("w = widget.get_allocated_width()", "get_allocated_width"),
    ("h = widget.get_allocated_height()", "get_allocated_height"),
    ("a = widget.get_allocation()", "get_allocation"),
    ("g = widget.get_window()", "get_window"),
    ("t = widget.get_toplevel()", "get_toplevel"),
    ("widget.set_margin_left(4)", "set_margin_left"),
    ("widget.set_margin_right(4)", "set_margin_right"),
    ("x = Gtk.Alignment()", "Gtk.Alignment"),
    ("x = Gtk.HBox()", "Gtk.HBox"),
    ("x = Gtk.VBox()", "Gtk.VBox"),
    ("x = Gtk.Table()", "Gtk.Table"),
    ("x = Gtk.Misc", "Gtk.Misc"),
    ("Gtk.render_background(ctx, cr, 0, 0, 1, 1)", "Gtk.render_background"),
    ("Gtk.render_frame(ctx, cr, 0, 0, 1, 1)", "Gtk.render_frame"),
    ("widget.modify_bg(0, None)", "modify_bg"),
    ("widget.modify_font(None)", "modify_font"),
    ("widget.set_no_show_all(True)", "set_no_show_all"),
    ("window.resize(800, 600)", "resize"),
    ("button.set_image(image)", "set_image"),
    ('widget.connect_after("draw", handler)', "'draw'"),
    ('widget.connect_after("key-press-event", handler)', "'key-press-event'"),
    ('widget.connect_object("delete-event", handler, other)', "'delete-event'"),
    ('getattr(window, "show_all")()', "'show_all'"),
    ('getattr(box, "pack_start")(child, True, True, 0)', "'pack_start'"),
    ('getattr(widget, "override_color")(0, None)', "'override_color'"),
    ('getattr(widget, "get_allocated_width")()', "'get_allocated_width'"),
    ('menu = getattr(Gtk, "Menu")()', "'Menu'"),
)


def test_every_evasion_is_caught_on_its_own_line(tmp_path: Path) -> None:
    bad = tmp_path / "evasions.py"
    bad.write_text("\n".join(line for line, _needle in EVASIONS) + "\n")
    problems = gtk4_lint.lint([bad])
    for number, (line, needle) in enumerate(EVASIONS, start=1):
        hits = [problem for problem in problems if f":{number}: " in problem]
        assert hits, f"not caught: {line}"
        assert any(needle in hit for hit in hits), (line, hits)


def test_name_bans_skip_files_that_cannot_hold_a_widget(tmp_path: Path) -> None:
    """``.add()`` / ``.resize()`` / ``.get_size()`` are a set, PIL and os in the (GTK-free) service layers."""
    service = tmp_path / "service.py"
    service.write_text(
        "from PIL import Image\n"
        "seen: set[int] = set()\n"
        "seen.add(1)\n"
        "small = image.resize((10, 10))\n"
        "columns = terminal.get_size()\n"
        "kids = node.get_children()\n"
    )
    assert gtk4_lint.lint([service]) == []


def test_service_files_still_get_the_gate_checks(tmp_path: Path) -> None:
    service = tmp_path / "service.py"
    service.write_text('from gi.repository import Gdk\nimport gi\ngi.require_version("Gdk", "3.0")\n')
    problems = "\n".join(gtk4_lint.lint([service]))
    assert "single version gate" in problems
    assert "require_version" in problems


def test_name_bans_apply_wherever_gtk_is_imported(tmp_path: Path) -> None:
    for number, gtk_import in enumerate(
        ("from src.gtk_version import Gtk", "from src.ui import compat", "import src.ui.compat", "import gi")
    ):
        ui = tmp_path / f"ui{number}.py"
        body = "box.add(child)\nwindow.resize(10, 10)\nseen.add(1)  # gtk4-lint: ok (a set)\n"
        ui.write_text(f"{gtk_import}\n{body}")
        problems = gtk4_lint.lint([ui])
        assert len(problems) == 2, (gtk_import, problems)
        assert ":2: " in problems[0] and ".add()" in problems[0]
        assert ":3: " in problems[1] and ".resize()" in problems[1]


def test_name_bans_apply_to_the_widget_layers_whatever_they_import() -> None:
    plain = gtk4_lint.ast.parse("x = 1")
    for relative in ("ui/x.py", "pages/x.py", "modules/x.py", "viewmodels/x.py", "main.py"):
        assert gtk4_lint._can_hold_widgets(PROJECT_ROOT / "src" / relative, plain), relative
    for layer in ("scanner", "catalogue", "imaging", "apply", "helper", "cli", "util", "config"):
        relative = f"src/{layer}/x.py"
        assert not gtk4_lint._can_hold_widgets(PROJECT_ROOT / relative, gtk4_lint.ast.parse("x = 1"))
        assert gtk4_lint._can_hold_widgets(PROJECT_ROOT / relative, gtk4_lint.ast.parse("import gi"))


def test_allowed_signals_and_names_pass(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text(
        "from src.gtk_version import Gtk\n"
        'button.connect("clicked", handler)\n'
        'button.connect_after("notify::visible", handler)\n'
        'value = getattr(widget, "route")\n'
        "widget.set_margin_start(4)\n"
        "box = Gtk.Box()\n"
    )
    assert gtk4_lint.lint([good]) == []


def test_only_the_gate_selects_the_gtk_version() -> None:
    hits = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src").rglob("*.py")
        if "require_version(" in path.read_text()
    ]
    assert hits == ["src/gtk_version.py"]
