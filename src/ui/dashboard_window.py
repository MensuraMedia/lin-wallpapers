"""Main application window: sidebar + content area, with remembered size and route."""

from __future__ import annotations

from typing import Any

from src import APP_NAME
from src.config.config_layout import Layout
from src.gtk_version import Gio, GLib, Gtk
from src.modules.manager_navigation import NavigationManager
from src.ui import compat
from src.ui.content_area import ContentArea
from src.ui.sidebar import NAV_ITEMS, Sidebar
from src.ui.window_state import WindowState

DEFAULT_ROUTE = NAV_ITEMS[0][1]


class DashboardWindow(Gtk.ApplicationWindow):  # type: ignore[misc]
    def __init__(self, application: Any, navigation_manager: NavigationManager) -> None:
        super().__init__(application=application, title=APP_NAME)
        self.nav_manager = navigation_manager
        self.state = WindowState()

        dims = Layout.dimensions
        self.set_size_request(dims.WINDOW_MIN_WIDTH, dims.WINDOW_MIN_HEIGHT)
        width, height = self.state.size((dims.WINDOW_DEFAULT_WIDTH, dims.WINDOW_DEFAULT_HEIGHT))
        self.set_default_size(max(width, dims.WINDOW_MIN_WIDTH), max(height, dims.WINDOW_MIN_HEIGHT))
        if self.state.maximized():
            self.maximize()

        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        compat.set_child(self, main_box)

        self.sidebar = Sidebar(self.nav_manager)
        self.sidebar.connect("page-changed", self.on_page_changed)
        compat.append(main_box, self.sidebar)

        self.content_area = ContentArea(self.nav_manager)
        compat.append(main_box, self.content_area, expand=True)

        navigate = Gio.SimpleAction.new("navigate", GLib.VariantType.new("s"))
        navigate.connect("activate", self.on_navigate_action)
        self.add_action(navigate)

        if not self.content_area.show_page(self.state.last_route(DEFAULT_ROUTE)):
            self.content_area.show_page(DEFAULT_ROUTE)

    def on_page_changed(self, _sidebar: Any, route: str) -> None:
        self.content_area.show_page(route)

    def on_navigate_action(self, _action: Any, parameter: Any) -> None:
        self.content_area.show_page(parameter.get_string())

    def save_state(self) -> None:
        width, height = compat.window_size(self)
        dims = Layout.dimensions
        # A destroyed window reports 0x0 or 1x1: anything under the minimum is not a size to remember.
        real = width >= dims.WINDOW_MIN_WIDTH and height >= dims.WINDOW_MIN_HEIGHT
        route = self.nav_manager.get_current_page()
        self.state.save(width, height, self.is_maximized(), route, keep_size=not real)
