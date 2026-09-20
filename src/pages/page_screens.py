"""Screens page — an M0 placeholder; filled in M3."""

from __future__ import annotations

from .page_base import BasePage


class ScreensPage(BasePage):
    route = "screens"
    title = "Screens"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("Desktop, lock screen, login screen, boot splash and boot menu.")
        self.add_placeholder(
            "M3",
            "Capability probes arrive in M3; applying in M4 (desktop, lock) and M5 (login, splash, menu).",
            [
                "One card per screen: mini preview, provider, mechanism and current image",
                "What was detected on this machine, with the evidence",
                "Unsupported screens stay visible, greyed out, and explain themselves",
                "Per-screen Apply and Revert, Apply everywhere, and the sync switch (M6)",
            ],
        )
