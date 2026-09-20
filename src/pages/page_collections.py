"""Collections page — an M0 placeholder; filled in M6."""

from __future__ import annotations

from .page_base import BasePage


class CollectionsPage(BasePage):
    route = "collections"
    title = "Collections"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("Group images by hand or by saved filter.")
        self.add_placeholder(
            "M6",
            "Collections and slideshows arrive in M6.",
            [
                "Manual collections",
                "Smart collections from saved filter queries",
                "A collection as a desktop slideshow source, where the desktop supports it",
            ],
        )
