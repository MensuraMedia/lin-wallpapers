"""Settings / About page — default fit, detected backend, version/credits."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from ... import __version__, imaging
from ...contextmenu import detect_context_provider
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

        integ = Adw.PreferencesGroup(
            title="Integration",
            description="Add images to your library straight from the file manager.",
        )
        self._provider = detect_context_provider()
        ctx = Adw.ActionRow(title="Add to file-manager right-click menu")
        if self._provider:
            ctx.set_subtitle(
                f"{self._provider.name} — right-click images → “Add to LinWallpaper”"
            )
            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            sw.set_active(self._provider.is_installed())
            sw.connect("notify::active", self._on_context_toggle)
            ctx.add_suffix(sw)
            ctx.set_activatable_widget(sw)
        else:
            ctx.set_subtitle("No supported file manager detected")
            ctx.set_sensitive(False)
        integ.add(ctx)
        page.add(integ)

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

    def _on_context_toggle(self, switch, _param) -> None:
        if not self._provider:
            return
        active = switch.get_active()
        try:
            if active:
                self._provider.install()
            else:
                self._provider.uninstall()
            self.state.settings.set("context_menu", active)
        except Exception as exc:  # keep the UI honest if the write fails
            self.win.toast(f"Couldn't update the right-click menu: {exc}")
            switch.set_active(self._provider.is_installed())
