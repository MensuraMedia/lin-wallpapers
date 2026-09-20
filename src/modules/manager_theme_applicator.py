"""Theme applicator (starter-template convention), driven by design tokens.

The starter generated CSS from Python color values. Here the colors live in ``tokens.css`` and
the applicator only decides *which files* to load: tokens, optional theme overrides, then the
component stylesheet — from the GResource bundle when it is built and not older than its sources,
else from ``resources/``. The ``font-family`` rules are generated from ``config_theme.Fonts``.
"""

from __future__ import annotations

from typing import Any

from src.config.config_paths import GRESOURCE_FILE, GRESOURCE_PREFIX
from src.config.config_theme import Theme, bundle_is_fresh, bundle_sources
from src.config.config_themes import ThemeDefinition
from src.gtk_version import Gio, GLib, Gtk
from src.ui import compat


class ThemeApplicator:
    """Loads the token and style sheets into one application-wide CSS provider."""

    def __init__(self) -> None:
        self.css_provider: Any = Gtk.CssProvider()
        self.current_theme: ThemeDefinition | None = None
        self._installed = False
        self._bundle_registered = False

    def _register_bundle(self) -> bool:
        if self._bundle_registered:
            return True
        if not bundle_is_fresh(GRESOURCE_FILE, bundle_sources()):
            return False  # missing, or stale: a CSS file was edited after the last ./run.sh
        try:
            Gio.resources_register(Gio.Resource.load(str(GRESOURCE_FILE)))
        except GLib.Error:
            return False
        self._bundle_registered = True
        return True

    def _read(self, name: str) -> str:
        if self._register_bundle():
            data = Gio.resources_lookup_data(f"{GRESOURCE_PREFIX}/css/{name}", Gio.ResourceLookupFlags.NONE)
            return bytes(data.get_data()).decode("utf-8")
        return (Theme.tokens_file.parent / name).read_text(encoding="utf-8")

    def build_css(self, theme_def: ThemeDefinition) -> str:
        parts = [self._read("tokens.css")]
        if theme_def.token_overrides is not None:
            parts.append(theme_def.token_overrides.read_text(encoding="utf-8"))
        parts.append(Theme.fonts.css())
        parts.append(self._read("style.css"))
        return "\n".join(parts)

    def apply_theme(self, theme_def: ThemeDefinition) -> None:
        self.css_provider.load_from_data(self.build_css(theme_def).encode("utf-8"))
        if not self._installed:
            compat.add_css_provider(self.css_provider)
            self._installed = True
        self.current_theme = theme_def
