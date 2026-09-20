"""GTK 3 / GTK 4 compatibility layer (TECHNICAL-CONCEPT §18).

Pages and components never call a GTK 3-only API directly; they call these helpers, and
``tools/gtk4_lint.py`` fails the build on banned calls anywhere else. This is the only module
allowed to branch on the GTK version, which keeps the M8 port mechanical.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gi.repository import GdkPixbuf

from src.gtk_version import IS_GTK4, Gdk, GLib, Gtk

__all__ = [
    "CanvasArea",
    "add_class",
    "add_css_provider",
    "append",
    "children",
    "clear_children",
    "click_gesture",
    "foreground_color",
    "icon",
    "image_from_bytes",
    "lookup_color",
    "on_close_request",
    "remove_class",
    "set_child",
    "set_tracked_text",
    "set_wrap",
    "show",
    "tracked",
    "window_size",
]


def append(box: Any, child: Any, *, expand: bool = False, padding: int = 0) -> None:
    """Append ``child`` to a ``Gtk.Box`` (``pack_start`` in GTK 3, ``append`` in GTK 4)."""
    if IS_GTK4:
        if expand:
            vertical = box.get_orientation() == Gtk.Orientation.VERTICAL
            child.set_vexpand(True) if vertical else child.set_hexpand(True)
        box.append(child)
    else:
        box.pack_start(child, expand, expand, padding)


def set_child(container: Any, child: Any) -> None:
    """Set the single child of a bin-like container (window, scrolled window, button)."""
    if IS_GTK4:
        container.set_child(child)
    else:
        container.add(child)


def show(widget: Any) -> None:
    """Make a widget tree visible. GTK 4 widgets are visible by default."""
    if IS_GTK4:
        widget.set_visible(True)
    else:
        widget.show_all()


def add_class(widget: Any, *names: str) -> None:
    for name in names:
        if IS_GTK4:
            widget.add_css_class(name)
        else:
            widget.get_style_context().add_class(name)


def remove_class(widget: Any, *names: str) -> None:
    for name in names:
        if IS_GTK4:
            widget.remove_css_class(name)
        else:
            widget.get_style_context().remove_class(name)


def set_wrap(label: Any, wrap: bool = True) -> None:
    if IS_GTK4:
        label.set_wrap(wrap)
    else:
        label.set_line_wrap(wrap)


def tracked(text: str) -> str:
    """Text for a label styled with ``letter-spacing`` of 1 px or more.

    GTK 3 measures such a label as if it wrapped at every space (twice the height for two words),
    so the spaces become non-breaking. Sub-pixel letter-spacing is ignored by GTK 3 altogether.
    """
    return text.replace(" ", "\u00a0")


def set_tracked_text(label: Any, text: str) -> None:
    """Show ``text`` on a letter-spaced label; assistive technology still reads the plain text.

    The non-breaking spaces of :func:`tracked` are a rendering workaround only, so the accessible
    name is set to ``text`` itself rather than derived from what the label displays.
    """
    label.set_text(tracked(text))
    if IS_GTK4:
        label.update_property([Gtk.AccessibleProperty.LABEL], [text])
    else:
        label.get_accessible().set_name(text)


def children(container: Any) -> list[Any]:
    """Every direct child of a container, oldest first — the portable ``get_children``."""
    if IS_GTK4:
        out: list[Any] = []
        child = container.get_first_child()
        while child is not None:
            out.append(child)
            child = child.get_next_sibling()
        return out
    return list(container.get_children())


def clear_children(container: Any) -> None:
    """Remove every child from a box-like container (for a grid or list that rebuilds in place)."""
    for child in children(container):
        container.remove(child)


def image_from_bytes(data: bytes, width: int, height: int) -> Any:
    """A widget showing raw image ``data`` (JPEG/PNG bytes from a view model), scaled to fit
    ``width`` × ``height`` preserving aspect. Returns ``None`` when the bytes will not decode.

    A ``GdkPixbuf`` in GTK 3, a ``Gdk.Texture`` behind a ``Gtk.Picture`` in GTK 4 — the one place
    the bytes→widget branch lives, so components stay version-independent.
    """
    if IS_GTK4:
        try:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
        except GLib.Error:
            return None
        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_size_request(width, height)
        picture.set_content_fit(Gtk.ContentFit.COVER)
        return picture
    loader = GdkPixbuf.PixbufLoader()
    try:
        loader.write(data)
        loader.close()
    except GLib.Error:
        return None
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        return None
    source_width, source_height = pixbuf.get_width(), pixbuf.get_height()
    if source_width <= 0 or source_height <= 0:
        return None
    scale = min(width / source_width, height / source_height)
    target = (max(1, round(source_width * scale)), max(1, round(source_height * scale)))
    scaled = pixbuf.scale_simple(target[0], target[1], GdkPixbuf.InterpType.BILINEAR)
    return Gtk.Image.new_from_pixbuf(scaled)


def icon(name: str, pixel_size: int = 16) -> Any:
    """A symbolic icon image from the icon theme."""
    image = Gtk.Image.new_from_icon_name(name) if IS_GTK4 else Gtk.Image.new_from_icon_name(name, 1)
    image.set_pixel_size(pixel_size)
    return image


def add_css_provider(provider: Any, priority: int | None = None) -> None:
    """Install a CSS provider for the whole application."""
    if priority is None:
        priority = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    if IS_GTK4:
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, priority)
    else:
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, priority)


def window_size(window: Any) -> tuple[int, int]:
    """The window's current (unmaximized) size, for remembering it."""
    if IS_GTK4 or window.is_maximized():
        width, height = window.get_default_size()
    else:
        width, height = window.get_size()
    return (int(width), int(height))


def lookup_color(widget: Any, token: str) -> tuple[float, float, float, float]:
    """Resolve a ``@define-color`` token to RGBA floats, for Cairo drawing.

    Raises ``KeyError`` for an unknown token: a color that is not a token is a bug, not a fallback.
    """
    found, rgba = widget.get_style_context().lookup_color(token)
    if not found:
        raise KeyError(f"unknown design token: {token}")
    return (rgba.red, rgba.green, rgba.blue, rgba.alpha)


def foreground_color(widget: Any) -> tuple[float, float, float, float]:
    """The widget's CSS ``color`` as RGBA floats, so drawn glyphs follow hover/active states."""
    if IS_GTK4:
        rgba = widget.get_color()
    else:
        context = widget.get_style_context()
        rgba = context.get_color(context.get_state())
    return (rgba.red, rgba.green, rgba.blue, rgba.alpha)


def on_close_request(window: Any, handler: Callable[[], None]) -> None:
    """Run ``handler()`` when the user closes the window; the close always proceeds."""

    def _closing(*_args: Any) -> bool:
        handler()
        return False

    window.connect("close-request" if IS_GTK4 else "delete-event", _closing)


def click_gesture(widget: Any, on_pressed: Callable[[int, float, float], None]) -> Any:
    """Attach a click gesture; ``on_pressed(n_press, x, y)``. Never ``button-press-event``."""

    def _pressed(_gesture: Any, n_press: int, x: float, y: float) -> None:
        on_pressed(n_press, x, y)

    if IS_GTK4:
        gesture = Gtk.GestureClick()
        widget.add_controller(gesture)
    else:
        gesture = Gtk.GestureMultiPress.new(widget)
    gesture.connect("pressed", _pressed)
    return gesture


class CanvasArea(Gtk.DrawingArea):  # type: ignore[misc]
    """A drawing area with one version-independent hook: override ``on_draw(cr, width, height)``."""

    def __init__(self, width: int = -1, height: int = -1) -> None:
        super().__init__()
        self.set_size_request(width, height)
        if IS_GTK4:
            self.set_draw_func(self._draw_gtk4)
        else:
            self.connect("draw", self._draw_gtk3)

    def _draw_gtk3(self, _widget: Any, cr: Any) -> bool:
        self.on_draw(cr, self.get_allocated_width(), self.get_allocated_height())
        return False

    def _draw_gtk4(self, _area: Any, cr: Any, width: int, height: int) -> None:
        self.on_draw(cr, width, height)

    def on_draw(self, cr: Any, width: int, height: int) -> None:
        raise NotImplementedError("CanvasArea subclasses implement on_draw(cr, width, height)")
