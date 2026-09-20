"""Browse page — an M0 placeholder; filled in M1."""

from __future__ import annotations

from .page_base import BasePage


class BrowsePage(BasePage):
    route = "browse"
    title = "Browse"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("Every image on this machine that could be a wallpaper.")
        self.add_placeholder(
            "M1",
            "Nothing has been scanned yet — the scanner and catalogue arrive in M1, scoring in M2.",
            [
                "A virtualized grid of image cards: thumbnail, filename, resolution chip",
                "Search, filters (resolution, aspect, orientation, format, source) and sorting",
                "The suitability score ring and badges on each card (M2)",
                "First-run hero proposing scan roots; nothing is scanned until you agree",
            ],
        )
