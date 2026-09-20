"""Preview page — an M0 placeholder; filled in M3."""

from __future__ import annotations

from .page_base import BasePage


class PreviewPage(BasePage):
    route = "preview"
    title = "Preview"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("See every screen before anything changes.")
        self.add_placeholder(
            "M3",
            "The transform pipeline and the Cairo preview compositor arrive in M3.",
            [
                "All five screens rendered from the same transform the apply will use",
                "Desktop with panel, lock with clock, greeter with its fields",
                "The boot splash with pixel-exact theme geometry",
                "The boot menu over the quantized image, so banding shows before install",
            ],
        )
