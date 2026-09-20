"""Content area (starter-template convention): a stack of pages, each with its own scroll state."""

from __future__ import annotations

from typing import Any

from src.gtk_version import Gtk
from src.pages import ALL_PAGES, PageContext, make_page
from src.ui import compat


class ContentArea(Gtk.Box):  # type: ignore[misc]
    def __init__(self, navigation_manager: Any, context: PageContext | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.nav_manager = navigation_manager
        # The window builds ContentArea with no context (contract: it never imports a view model), so pull
        # the injected one off the running application; None in a bare shell falls back to empty pages.
        self.context = context if context is not None else _app_context()
        compat.add_class(self, "content-area")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        compat.append(self, self.stack, expand=True)

        self.nav_manager.set_page_stack(self.stack)
        self.register_pages()

    def register_pages(self) -> None:
        for page_class in ALL_PAGES:
            page = make_page(page_class, self.context)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            compat.set_child(scrolled, page)
            self.stack.add_named(scrolled, page.route)
            self.nav_manager.register_page(page.route, page)

    def show_page(self, route: str) -> bool:
        return bool(self.nav_manager.navigate_to(route))


def _app_context() -> PageContext | None:
    """The :class:`PageContext` the application stored on itself in ``do_activate`` (see ``src/main.py``)."""
    app = Gtk.Application.get_default()
    return getattr(app, "page_context", None) if app is not None else None
