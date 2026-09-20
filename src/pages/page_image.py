"""Image page — an M0 placeholder; filled in M2."""

from __future__ import annotations

from .page_base import BasePage


class ImagePage(BasePage):
    route = "image"
    title = "Image"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("One image in detail.")
        self.add_placeholder(
            "M2",
            "The image page arrives with scoring in M2; the crop frame and fit modes follow in M3.",
            [
                "Large preview with true dimensions and format",
                "Score breakdown, component by component, with reasons",
                "Metadata, palette swatches and self-explaining badges",
                "Fit mode and drag-to-position focal point (M3)",
                "The five screen tiles showing where this image is already set",
            ],
        )
