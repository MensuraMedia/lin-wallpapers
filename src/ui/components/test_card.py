"""The Test page's single card and its right-click menu (self-contained, plain-widget clean room).

This module is the whole point of the Test page: a plain ``Gtk.Box`` card — deliberately **not** inside a
``Gtk.FlowBox`` — whose real secondary-click gesture opens a context menu at the click point. It reuses
the shared ``compat`` gesture/popover helpers and ``open_context_menu``, so a real right-click is proven
on an ordinary widget (the Browse grid's card is identical but sits inside a ``FlowBoxChild`` that claims
the button event first). *Exclude Image* hides the card and offers Undo in the page's toast; *Details*
reveals the image path and dimensions; *Add to Collection* and *Preview…* are shown disabled with their
milestone reason, matching the app convention (§15). The component takes plain values and a toast — never
a view model or the filesystem.
"""

from __future__ import annotations

from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk, Pango
from src.ui import compat
from src.ui.components.context_menu import MenuAction, open_context_menu

THUMB_WIDTH = 320
THUMB_HEIGHT = 200


class TestCard(Gtk.Box):  # type: ignore[misc]
    """A plain, non-``FlowBox`` image card with a working right-click context menu."""

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, image: Any, toast: Any) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.XSMALL)
        self._image = image
        self._toast = toast
        self.menu: Any = None  # the popover the last real right-click opened; None until one fires
        self._details: Any = None
        compat.add_class(self, "image-card")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.XSMALL)

        thumb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        thumb.set_size_request(THUMB_WIDTH, THUMB_HEIGHT)
        thumb.set_halign(Gtk.Align.CENTER)
        thumb.set_valign(Gtk.Align.CENTER)
        compat.add_class(thumb, "thumb")
        picture = compat.image_from_bytes(image.data, THUMB_WIDTH, THUMB_HEIGHT) if image.data else None
        if picture is not None:
            compat.append(thumb, picture)
        else:
            placeholder = Gtk.Label(label="No preview")
            compat.add_class(placeholder, "thumb-empty")
            compat.append(thumb, placeholder)
        compat.append(content, thumb)

        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.XSMALL)
        name = Gtk.Label(label=image.name)
        name.set_xalign(0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_hexpand(True)
        compat.add_class(name, "card-name")
        compat.append(meta, name, expand=True)
        if image.width and image.height:
            chip = Gtk.Label(label=f"{image.width}×{image.height}")
            compat.add_class(chip, "res-chip", "tabular")
            compat.append(meta, chip)
        compat.append(content, meta)

        # The single thing this page proves: a real (pointer) right-click opens the menu. The gesture must
        # sit on a widget that OWNS a GdkWindow, or a real click never reaches it (compat.click_target).
        self.click_target = compat.click_target(content)
        compat.append(self, self.click_target)
        compat.secondary_click_gesture(self.click_target, self._open_menu)

    def _open_menu(self, _n_press: int, x: float, y: float) -> None:
        actions: list[MenuAction | None] = [
            MenuAction("Exclude Image", self._exclude),
            MenuAction("Details", self._show_details),
            None,
            MenuAction("Add to Collection", enabled=False, reason="Arrives in M6"),
            MenuAction("Preview…", enabled=False, reason="Arrives in M3"),
        ]
        self.menu = open_context_menu(self.click_target, x, y, actions)

    def _exclude(self) -> None:
        self.set_visible(False)
        self._toast.show_message(f"Excluded {self._image.name} · Undo", self._restore)

    def _restore(self) -> None:
        compat.show(self)

    def _show_details(self) -> None:
        if self._details is None:
            self._details = Gtk.Label()
            self._details.set_xalign(0)
            compat.set_wrap(self._details)
            compat.add_class(self._details, "dim")
            compat.append(self, self._details)
        self._details.set_text(f"{self._image.path} · {self._image.width}×{self._image.height}")
        compat.show(self._details)
