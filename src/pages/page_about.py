"""About page — opened from Settings rather than the sidebar."""

from __future__ import annotations

from src import APP_ID, APP_NAME, __version__

from .page_base import BasePage


class AboutPage(BasePage):
    route = "about"
    title = "About"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle(f"{APP_NAME} {__version__} — one wallpaper, every screen.")
        self.add_paragraph(
            "Lin Wallpapers is a window, not a service: it writes ordinary operating-system "
            "configuration and exits. No daemon, nothing enabled at boot, no telemetry."
        )
        self.add_paragraph(f"Application ID: {APP_ID}")
        self.add_paragraph(
            "Free to use, modify and distribute; commercial use requires prior written permission. "
            "Application shell derived from gtk-python-dashboard-starter by mikesdatawork."
        )
