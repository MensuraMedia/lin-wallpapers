"""Base page (starter-template convention): subclasses implement ``build_content()``."""

from __future__ import annotations

from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat


class BasePage(Gtk.Box):  # type: ignore[misc]
    """All pages inherit from this class and implement :meth:`build_content`."""

    route = ""
    title = ""

    def __init__(
        self, spacing: int = Layout.spacing.PAGE_GAP, margin: int = Layout.dimensions.CONTENT_MARGIN
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        self.set_margin_start(margin)
        self.set_margin_end(margin)
        self.set_margin_top(Layout.dimensions.CONTENT_MARGIN_TOP)
        self.set_margin_bottom(Layout.dimensions.CONTENT_MARGIN_TOP)
        self.header: Any = None
        self.build_content()

    def build_content(self) -> None:
        raise NotImplementedError("Subclasses must implement build_content()")

    def _label(self, text: str, css_class: str | None = None, wrap: bool = False) -> Any:
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        if wrap:
            compat.set_wrap(label)
        if css_class:
            compat.add_class(label, css_class)
        return label

    def add_title(self, text: str) -> Any:
        """The page header: the title, with the subtitle (if any) 3 px under it."""
        self.header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.HEADER_GAP)
        label = self._label(text, "page-title")
        compat.append(self.header, label)
        compat.append(self, self.header)
        return label

    def add_subtitle(self, text: str) -> Any:
        label = self._label(text, "page-subtitle", wrap=True)
        compat.append(self.header if self.header is not None else self, label)
        return label

    def add_paragraph(self, text: str) -> Any:
        label = self._label(text, wrap=True)
        compat.append(self, label)
        return label

    def add_placeholder(self, milestone: str, summary: str, contents: list[str]) -> Any:
        """The M0 empty state: names the milestone that fills the page. No fake data, ever."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.SMALL)
        compat.add_class(card, "card")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.SMALL)
        chip = Gtk.Label(label=f"ARRIVES IN {milestone}")
        compat.add_class(chip, "chip", "accent")
        compat.append(header, chip)
        compat.append(card, header)

        compat.append(card, self._label(summary, wrap=True))
        eyebrow = self._label("", "eyebrow")
        compat.set_tracked_text(eyebrow, "WHAT WILL LIVE HERE")
        compat.append(card, eyebrow)
        for line in contents:
            compat.append(card, self._label(f"•  {line}", "dim", wrap=True))

        compat.append(self, card)
        return card
