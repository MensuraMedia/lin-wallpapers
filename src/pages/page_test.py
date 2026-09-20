"""Test page: one real local image on a single plain card, to verify a real right-click (dev harness).

The Browse right-click passes its tests but does not fire on a live right-click, because the
``Gtk.FlowBox``/``FlowBoxChild`` around each card claims the button event first. This page is the
clean-room proof: one :class:`TestCard` — a plain widget, no FlowBox — whose secondary-click gesture
opens a context menu at the pointer. The single image comes from the injected ``TestVM`` (catalogue
first, else a standard picture directory); when nothing is found, a real empty state says so. No fake data.
"""

from __future__ import annotations

from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat
from src.ui.components.test_card import TestCard
from src.ui.components.toast import Toast

from .page_base import BasePage


class TestPage(BasePage):
    __test__ = False  # not a pytest test class, despite the name

    route = "test"
    title = "Test"
    wants_context = True

    def __init__(self, context: Any = None) -> None:
        self.context = context
        self.card: Any = None  # the loaded TestCard, or None (empty state / not yet loaded)
        self.loaded = False
        super().__init__()

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("One real local image on a plain card, to verify a real right-click.")
        self.add_paragraph(
            "Right-click the card below — the context menu must open at the pointer. This page exists to "
            "prove that works on a plain widget (no FlowBox), unlike the Browse grid."
        )

        self._vm: Any = getattr(self.context, "test_vm", None)

        self._holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.SMALL)
        self._holder.set_halign(Gtk.Align.START)
        compat.append(self, self._holder)

        self._toast = Toast()
        compat.append(self, self._toast)

        if self._vm is None:
            self._show_message("The image source is unavailable — the catalogue could not be opened.")
            self.loaded = True
            return
        self._vm.load(self._on_loaded)

    def _on_loaded(self, image: Any) -> None:
        self.loaded = True
        compat.clear_children(self._holder)
        self.card = None
        if image is None:
            self._show_message("No local image found — scan a folder first.")
            return
        self.card = TestCard(image, self._toast)
        compat.append(self._holder, self.card)
        compat.show(self._holder)

    def _show_message(self, text: str) -> None:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.XSMALL)
        compat.add_class(card, "card", "empty-state")
        compat.append(card, self._label("Nothing to show", "hero-title"))
        compat.append(card, self._label(text, "dim", wrap=True))
        compat.append(self._holder, card)
        compat.show(self._holder)
