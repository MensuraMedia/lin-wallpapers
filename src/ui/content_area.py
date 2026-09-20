"""Content area (starter-template convention): a stack of pages, each with its own scroll state."""

from __future__ import annotations

from typing import Any

from src.gtk_version import Gtk
from src.pages import ALL_PAGES
from src.ui import compat


class ContentArea(Gtk.Box):  # type: ignore[misc]
    def __init__(self, navigation_manager: Any) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.nav_manager = navigation_manager
        compat.add_class(self, "content-area")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        compat.append(self, self.stack, expand=True)

        self.nav_manager.set_page_stack(self.stack)
        self.register_pages()

    def register_pages(self) -> None:
        for page_class in ALL_PAGES:
            page = page_class()
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            compat.set_child(scrolled, page)
            self.stack.add_named(scrolled, page.route)
            self.nav_manager.register_page(page.route, page)

    def show_page(self, route: str) -> bool:
        return bool(self.nav_manager.navigate_to(route))
