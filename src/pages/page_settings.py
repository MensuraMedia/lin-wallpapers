"""Settings page — an M0 placeholder; filled in M1."""

from __future__ import annotations

from src.gtk_version import GLib, Gtk
from src.ui import compat

from .page_base import BasePage


class SettingsPage(BasePage):
    route = "settings"
    title = "Settings"

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("Scanning, cache, defaults and diagnostics.")
        self.add_placeholder(
            "M1",
            "Settings fill in as features land: scan policy and cache in M1, sync and diagnostics in M6.",
            [
                "Scan policy, thumbnail cache size and default fit mode",
                "Sync behavior and the polkit rule state (M6)",
                "Clear cache, rebuild catalogue, export and import settings",
                "Diagnostics: the activity log and capability table (M6)",
            ],
        )

        about = Gtk.Button(label="About Lin Wallpapers")
        compat.add_class(about, "pill")
        about.set_halign(Gtk.Align.START)
        about.set_action_name("win.navigate")
        about.set_action_target_value(GLib.Variant("s", "about"))
        compat.append(self, about)
