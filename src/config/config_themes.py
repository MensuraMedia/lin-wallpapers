"""Theme definitions (starter-template convention).

A theme is a set of overrides for the tokens in ``tokens.css``. The Lin Wallpapers theme is the
default and overrides nothing — the token file already *is* that theme. Further themes would
name other token files rather than carry color values in Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ThemeDefinition:
    """A named theme: an optional token file layered over ``tokens.css``."""

    name: str
    token_overrides: Path | None = None


DEFAULT_THEME = "lin-wallpapers"

THEMES: dict[str, ThemeDefinition] = {
    DEFAULT_THEME: ThemeDefinition(name="Lin Wallpapers (yellow / gray)"),
}


def get_theme(theme_id: str) -> ThemeDefinition:
    """Theme by id, falling back to the default."""
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME])


def get_all_themes() -> dict[str, ThemeDefinition]:
    return THEMES
