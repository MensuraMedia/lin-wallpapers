"""The Browse card right-click menu (M1.7, docs/design/browse-context-menu.md; mockup BrowseMenu.png).

A ``Gtk.Popover`` of flat button rows over one image card: *Exclude Image* and *Exclude Folder* are live,
while *Add to Collection* and *Preview…* are shown **disabled with a reason** — never hidden (§15). The
component is pure GTK-through-``compat``: it takes plain callbacks and never sees a view model or a path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat


@dataclass(frozen=True)
class MenuAction:
    label: str
    on_activate: Callable[[], None] | None = None
    enabled: bool = True
    reason: str | None = None  # the tooltip a disabled row carries (why, and which milestone)


def open_context_menu(parent: Any, x: float, y: float, actions: list[MenuAction | None]) -> Any:
    """Pop a menu up at ``(x, y)`` in ``parent``; ``None`` in ``actions`` renders a separator."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    compat.add_class(box, "context-menu")
    popover: dict[str, Any] = {}

    for action in actions:
        if action is None:
            separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            compat.add_class(separator, "context-menu-sep")
            compat.append(box, separator)
            continue
        button = Gtk.Button(label=action.label)
        compat.add_class(button, "flat", "context-menu-item")
        button.set_sensitive(action.enabled)
        if not action.enabled and action.reason is not None:
            button.set_tooltip_text(action.reason)
        if action.enabled and action.on_activate is not None:
            button.connect("clicked", _activate, popover, action.on_activate)
        compat.append(box, button)

    box.set_size_request(Layout.dimensions.CONTEXT_MENU_WIDTH, -1)
    popover["widget"] = compat.menu_popover(parent, box, x, y)
    return popover["widget"]


def _activate(_button: Any, popover: dict[str, Any], handler: Callable[[], None]) -> None:
    widget = popover.get("widget")
    if widget is not None:
        widget.popdown()
    handler()
