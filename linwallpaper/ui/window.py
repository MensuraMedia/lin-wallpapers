"""The application window: sidebar + Adw.ViewStack + toast overlay."""

from __future__ import annotations

from gi.repository import Adw, Gio, Gtk

from .. import APP_ID, APP_TITLE, imaging
from ..backends import detect_backend
from ..monitors import desktop_name, list_monitors
from .pages.preview import PreviewPage
from .pages.screens import ScreensPage
from .pages.settings import SettingsPage
from .pages.wallpaper import WallpaperPage
from .sidebar import Sidebar
from .state import AppState


class AppWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app)
        self.set_title(APP_TITLE)
        self.set_default_size(1180, 760)
        self.set_icon_name(APP_ID)  # taskbar/menu icon once installed
        self.add_css_class("linwallpaper")

        try:
            monitors = list_monitors()
        except Exception:
            monitors = []
        backend = detect_backend()
        self.state = AppState(backend=backend, monitors=monitors, desktop=desktop_name())

        self.stack = Adw.ViewStack()
        self._pages: dict[str, Gtk.Widget] = {}

        self.sidebar = Sidebar(self.state, self.navigate)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.add_css_class("lw-root")
        root.append(self.sidebar)
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.stack)
        root.append(scroller)

        self.toaster = Adw.ToastOverlay()
        self.toaster.set_child(root)
        self.set_content(self.toaster)

        # register pages (starter convention)
        for page_cls in (WallpaperPage, ScreensPage, PreviewPage, SettingsPage):
            page = page_cls(self.state, self)
            self.register_page(page.route, page)

        self.sidebar.select("wallpaper")
        self.navigate("wallpaper")

    # ---- page registry ----------------------------------------------------
    def register_page(self, route: str, page: Gtk.Widget) -> None:
        self._pages[route] = page
        self.stack.add_named(page, route)

    def navigate(self, route: str) -> None:
        if route in self._pages:
            self.stack.set_visible_child_name(route)
            self.sidebar.select(route)  # keep the sidebar highlight in sync
            page = self._pages[route]
            if hasattr(page, "refresh"):
                page.refresh()

    # ---- services used by pages -------------------------------------------
    def open_image_dialog(self, on_chosen=None) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Open image")
        filt = Gtk.FileFilter()
        filt.set_name("Images")
        for mime in imaging.supported_mime_types():
            filt.add_mime_type(mime)
        # Also match by extension: mime sniffing can miss files, but the pixbuf
        # loaders enumerate every extension they accept — belt and braces.
        for fmt in imaging.supported_formats():
            for ext in fmt["extensions"]:
                filt.add_suffix(ext)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        dialog.set_filters(filters)
        dialog.set_default_filter(filt)

        def cb(dlg, result):
            try:
                gfile = dlg.open_finish(result)
            except Exception:
                return
            if gfile is None:
                return
            path = gfile.get_path()
            if not path:
                return
            self.load_image(path, on_chosen)

        dialog.open(self, None, cb)

    def load_image(self, path: str, on_ok=None) -> bool:
        """Validate ``path`` then set it (or call ``on_ok``); toast on failure.

        Central gate for every way an image enters the app (Open dialog,
        per-screen chooser, drag-and-drop) so a bad/missing/corrupt file shows
        an inline error and never crashes.
        """
        ok, reason = imaging.validate(path)
        if not ok:
            self.toast(f"Can't open image: {reason}")
            return False
        if on_ok:
            on_ok(path)
        else:
            self.state.set_image(path)
        return True

    def apply(self, target: str) -> None:
        if not self.state.image_path or not self.state.backend:
            self.toast("Nothing to apply")
            return
        try:
            result = self.state.backend.apply(
                self.state.image_path, self.state.fit, self.state.monitors, target
            )
        except Exception as exc:  # surface the failure, do not pretend success
            self.toast(f"Apply failed: {exc}")
            return
        self.state.last_apply = result
        where = "all screens" if result.target == "all" else result.target
        toast = Adw.Toast.new(f"Applied to {where}")
        toast.set_button_label("Undo")
        toast.set_timeout(6)
        toast.connect("button-clicked", lambda *_: self._undo(result))
        self.toaster.add_toast(toast)

    def _undo(self, result) -> None:
        try:
            self.state.backend.restore(result.previous)
            self.toast("Reverted")
        except Exception as exc:
            self.toast(f"Undo failed: {exc}")

    def toast(self, message: str) -> None:
        self.toaster.add_toast(Adw.Toast.new(message))
