"""Sources page — an M0 placeholder; filled in M1."""

from __future__ import annotations

from .page_base import BasePage


class SourcesPage(BasePage):
    route = "sources"
    title = "Sources"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("Where wallpapers come from.")
        self.add_placeholder(
            "M1",
            "Scan roots and the scanner arrive in M1.",
            [
                "Picture folders, system wallpaper directories, mounted volumes and added folders",
                "Per-root image counts, last scan and live progress",
                "Network mounts excluded by default, with the reason shown",
                "The skipped list and the exclusions editor",
            ],
        )
