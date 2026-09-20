#!/usr/bin/env python3
"""GTK 4 portability guard (TECHNICAL-CONCEPT §18).

Fails on GTK 3-only API used in ``src/`` outside ``src/ui/compat.py``, and on GTK being imported or
version-gated anywhere but ``src/gtk_version.py``.

The API bans go by *name* (``.add()``, ``.get_size()``, ``.resize()`` …), so they apply only to
modules that can hold a widget: the widget layers (``src/ui``, ``src/pages``, ``src/modules``,
``src/main.py``) and any file that imports ``gi``, ``src.gtk_version`` or ``src.ui``. The service
layers get the import/gate checks only — ``set.add()`` and PIL's ``Image.resize()`` are not GTK, and
import-linter already keeps GTK out of those layers. ``src/viewmodels`` is gi-free by contract (only
``gdk_displays.py`` imports the GTK gate, and that file is still caught by the import rule above), so
the view models are treated as a service layer — a plain ``selection.add()`` there is not a widget call.
A line can still opt out with ``# gtk4-lint: ok`` and a reason.

    python3 tools/gtk4_lint.py [paths...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPAT = ROOT / "src" / "ui" / "compat.py"
GATE = ROOT / "src" / "gtk_version.py"
PRAGMA = "gtk4-lint: ok"

# method names that exist only in GTK 3 (or changed meaning in GTK 4)
BANNED_CALLS = {
    "pack_start": "compat.append()",
    "pack_end": "compat.append()",
    "add": "compat.set_child() / compat.append()",
    "show_all": "compat.show()",
    "set_line_wrap": "compat.set_wrap()",
    "get_style_context": "compat.add_class() / compat.lookup_color()",
    "add_provider_for_screen": "compat.add_css_provider()",
    "set_relief": "the 'flat' CSS class",
    "set_border_width": "margins",
    "get_size": "compat.window_size()",
    "get_children": "iterate with get_first_child()/get_next_sibling() behind compat",
    "set_position": "nothing — GTK 4 windows are placed by the compositor",
    "get_allocated_width": "get_width() behind compat (compat.CanvasArea passes the size to on_draw)",
    "get_allocated_height": "get_height() behind compat (compat.CanvasArea passes the size to on_draw)",
    "get_allocation": "get_width()/get_height() behind compat",
    "get_window": "get_surface() behind compat",
    "get_toplevel": "get_root() behind compat",
    "set_margin_left": "set_margin_start()",
    "set_margin_right": "set_margin_end()",
    "set_no_show_all": "set_visible() — GTK 4 has no show_all",
    "set_image": "compat.set_child() with an image",
    "resize": "set_default_size()",
}
BANNED_PREFIXES = {
    "override_": "CSS classes and tokens",  # override_background_color & co.
    "modify_": "CSS classes and tokens",  # modify_bg, modify_fg, modify_font
}
CONNECT_METHODS = {"connect", "connect_after", "connect_object", "connect_object_after"}
GTK_MODULES = ("gi", "src.gtk_version", "src.ui")
WIDGET_LAYERS = tuple(ROOT / "src" / layer for layer in ("ui", "pages", "modules"))
WIDGET_FILES = (ROOT / "src" / "main.py",)

# attribute chains that must not appear
BANNED_ATTRS = {
    ("Gtk", "Menu"): "Gio.Menu + Gtk.Popover",
    ("Gtk", "MenuItem"): "Gio.Menu + Gtk.Popover",
    ("Gtk", "StatusIcon"): "nothing — no tray icon (the app is not a service)",
    ("Gtk", "EventBox"): "a gesture from compat",
    ("Gtk", "main"): "Gtk.Application.run()",
    ("Gtk", "main_quit"): "Gtk.Application.quit()",
    ("Gdk", "Screen"): "compat.add_css_provider()",
    ("Gtk", "Alignment"): "halign/valign and margins",
    ("Gtk", "HBox"): "Gtk.Box(orientation=HORIZONTAL)",
    ("Gtk", "VBox"): "Gtk.Box(orientation=VERTICAL)",
    ("Gtk", "Table"): "Gtk.Grid",
    ("Gtk", "Misc"): "xalign/yalign and margins",
}
# Gtk.render_background() & co. took a StyleContext; GTK 4 draws through snapshots.
BANNED_ATTR_PREFIXES = {("Gtk", "render_"): "a CanvasArea drawing from tokens"}

# GTK 3 event signals, replaced by gestures / event controllers
BANNED_SIGNALS = {
    "button-press-event",
    "button-release-event",
    "motion-notify-event",
    "key-press-event",
    "key-release-event",
    "scroll-event",
    "delete-event",
    "draw",
}


def _banned_name(name: str) -> str | None:
    """The replacement advice for a banned method name, or None when the name is allowed."""
    if name in BANNED_CALLS:
        return BANNED_CALLS[name]
    for prefix, advice in BANNED_PREFIXES.items():
        if name.startswith(prefix):
            return advice
    return None


def _banned_attr(owner: str, attr: str) -> str | None:
    if (owner, attr) in BANNED_ATTRS:
        return BANNED_ATTRS[(owner, attr)]
    for (prefix_owner, prefix), advice in BANNED_ATTR_PREFIXES.items():
        if owner == prefix_owner and attr.startswith(prefix):
            return advice
    return None


def _can_hold_widgets(path: Path, tree: ast.AST) -> bool:
    """A widget-layer module, or any module that imports GTK (``from src.ui import compat`` included)."""
    if path in WIDGET_FILES or any(path.is_relative_to(layer) for layer in WIDGET_LAYERS):
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        if any(module == root or module.startswith(root + ".") for module in modules for root in GTK_MODULES):
            return True
    return False


def _gate_problem(node: ast.AST) -> str | None:
    """Every file: GTK comes from the single version gate, and only the gate selects a version."""
    gate_message = "import Gtk/Gdk from src.gtk_version, the single version gate"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "require_version":
            return "gi.require_version() belongs in src/gtk_version.py only"
        return None
    if isinstance(node, ast.ImportFrom):
        names = {alias.name for alias in node.names}
        if (
            (node.module == "gi.repository" and names & {"Gtk", "Gdk"})
            or (node.module == "gi" and "repository" in names)
            or node.module in ("gi.repository.Gtk", "gi.repository.Gdk")
        ):
            return gate_message
    if isinstance(node, ast.Import):
        gated = ("gi.repository", "gi.repository.Gtk", "gi.repository.Gdk")
        if any(alias.name in gated for alias in node.names):
            return gate_message
    return None


def _api_problem(node: ast.AST) -> str | None:
    """Widget-capable files: GTK 3-only methods, classes, signals — also when reached through getattr()."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        name = node.func.attr
        advice = _banned_name(name)
        if advice is not None:
            return f".{name}() is GTK 3-only — use {advice}"
        if name in CONNECT_METHODS and node.args and isinstance(node.args[0], ast.Constant):
            signal = str(node.args[0].value).split("::")[0]
            if signal in BANNED_SIGNALS:
                return f"signal {signal!r} is GTK 3-only — use a compat gesture/controller"
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
        # getattr(widget, "show_all") is the same call, spelled to slip past an attribute check.
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            name = str(node.args[1].value)
            owner = node.args[0].id if isinstance(node.args[0], ast.Name) else ""
            advice = _banned_name(name) or _banned_attr(owner, name)
            if advice is not None:
                return f"getattr(…, {name!r}) reaches a GTK 3-only API — use {advice}"
    elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        advice = _banned_attr(node.value.id, node.attr)
        if advice is not None:
            return f"{node.value.id}.{node.attr} is GTK 3-only — use {advice}"
    return None


def _lint_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    problems: list[str] = []

    def report(node: ast.AST, message: str) -> None:
        line = getattr(node, "lineno", 0)
        if 0 < line <= len(lines) and PRAGMA in lines[line - 1]:
            return
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        problems.append(f"{shown}:{line}: {message}")

    tree = ast.parse(source, filename=str(path))
    widgets = _can_hold_widgets(path, tree)

    for node in ast.walk(tree):
        if path != GATE:
            message = _gate_problem(node)
            if message is not None:
                report(node, message)
        if widgets:
            message = _api_problem(node)
            if message is not None:
                report(node, message)
    return problems


def lint(paths: list[Path]) -> list[str]:
    problems: list[str] = []
    for base in paths:
        files = sorted(base.rglob("*.py")) if base.is_dir() else [base]
        for path in files:
            if path.resolve() != COMPAT:
                problems.extend(_lint_file(path.resolve()))
    return problems


def main(argv: list[str]) -> int:
    targets = [Path(arg) for arg in argv[1:]] or [ROOT / "src"]
    problems = lint(targets)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"gtk4_lint: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("gtk4_lint: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
