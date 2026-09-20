"""Settings / About page — default fit, detected backend, version/credits."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from ... import __version__, imaging
from .base import BasePage


class SettingsPage(BasePage):
    route = "settings"
    title = "Settings"
    subtitle = "Defaults, the detected desktop, and about."

    def build_content(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        page.set_vexpand(True)

        group = Adw.PreferencesGroup(title="Defaults")
        fit_row = Adw.ComboRow(title="Default fit mode")
        model = Gtk.StringList()
        for fit in imaging.FITS:
            model.append(imaging.FIT_LABELS[fit])
        fit_row.set_model(model)
        fit_row.set_selected(list(imaging.FITS).index(self.state.fit))
        fit_row.connect("notify::selected", self._on_fit)
        group.add(fit_row)
        page.add(group)

        env = Adw.PreferencesGroup(title="Environment")
        desk = Adw.ActionRow(title="Desktop session", subtitle=self.state.desktop)
        env.add(desk)
        if self.state.backend:
            usable, reason = self.state.backend.available()
            be = Adw.ActionRow(
                title="Wallpaper backend",
                subtitle=f"{self.state.backend.name}" + ("" if usable else f"  — unsupported: {reason}"),
            )
        else:
            be = Adw.ActionRow(title="Wallpaper backend", subtitle="none detected")
        env.add(be)
        native = bool(self.state.backend and self.state.backend.supports_per_monitor)
        per = Adw.ActionRow(
            title="Per-monitor images",
            subtitle="Native" if native else "Via composite (spanned)",
        )
        env.add(per)
        page.add(env)

        about = Adw.PreferencesGroup(title="About")
        about.add(
            Adw.ActionRow(title="LinWallpaper", subtitle=f"Version {__version__} · GTK 4 + libadwaita")
        )
        about.add(
            Adw.ActionRow(
                title="Scope",
                subtitle="Desktop background only · no root · no daemon · one-shot",
            )
        )
        page.add(about)
        return page

    def _on_fit(self, row, _param) -> None:
        idx = row.get_selected()
        if 0 <= idx < len(imaging.FITS):
            self.state.set_fit(imaging.FITS[idx])
