"""History page — an M0 placeholder; filled in M4."""

from __future__ import annotations

from .page_base import BasePage


class HistoryPage(BasePage):
    route = "history"
    title = "History"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("Every apply, and the way back.")
        self.add_placeholder(
            "M4",
            "The apply transaction and its history arrive in M4.",
            [
                "Each apply with its image, screens, result and backup",
                "Undo, re-apply and the backup manifest for every entry",
                "Rolled-back attempts with the step that failed and why",
            ],
        )
