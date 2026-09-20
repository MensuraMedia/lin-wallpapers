"""Design tokens. ``resources/css/tokens.css`` is the single source of truth for color.

No hex value lives in Python: code that needs a color outside GTK CSS (Cairo previews from M3,
tests) reads it from the token file through :func:`load_tokens`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from .config_paths import CSS_DIR, RESOURCES_DIR

TOKENS_FILE = CSS_DIR / "tokens.css"
STYLE_FILE = CSS_DIR / "style.css"
BUNDLE_MANIFEST = RESOURCES_DIR / "lin-wallpapers.gresource.xml"

# The palette of ui-kit-yellow-gray-yello.jpg (TECHNICAL-CONCEPT §16), by token name.
TOKEN_NAMES = (
    "bg-base",
    "bg-surface",
    "bg-raised",
    "stroke",
    "text",
    "text-dim",
    "accent",
    "accent-2",
    "on-accent",
    "ok",
    "warn",
    "danger",
)

_DEFINE = re.compile(r"@define-color\s+([A-Za-z_][\w-]*)\s+([^;]+);")


def load_tokens(path: Path = TOKENS_FILE) -> dict[str, str]:
    """Parse ``@define-color name value;`` lines into a dict."""
    return {name: value.strip() for name, value in _DEFINE.findall(path.read_text(encoding="utf-8"))}


def bundle_sources() -> list[Path]:
    """Every file compiled into the GResource bundle, plus its manifest."""
    return [*sorted(CSS_DIR.glob("*.css")), BUNDLE_MANIFEST]


def bundle_is_fresh(bundle: Path, sources: Iterable[Path]) -> bool:
    """True when ``bundle`` exists and is not older than any of ``sources`` that exist.

    Only ``run.sh`` rebuilds the bundle, so a CSS edit followed by a bare ``pytest`` would otherwise
    render the old styles. Sources that are absent (an installed package ships only the bundle) are ignored.
    """
    try:
        built = bundle.stat().st_mtime_ns
    except OSError:
        return False
    for source in sources:
        try:
            if source.stat().st_mtime_ns > built:
                return False
        except OSError:
            continue
    return True


def _css_family(stack: str) -> str:
    families = [family.strip() for family in stack.split(",")]
    return ", ".join(f'"{family}"' if " " in family else family for family in families)


class Fonts:
    """Font configuration: the Ubuntu family everywhere. The single source of the font stacks —
    style.css has no ``font-family``; the theme applicator loads :meth:`css` ahead of it."""

    FAMILY = "Ubuntu, Cantarell, sans-serif"
    FAMILY_MONO = "Ubuntu Mono, DejaVu Sans Mono, monospace"

    @classmethod
    def css(cls) -> str:
        """The generated ``font-family`` rules: the UI stack everywhere, the mono stack on ``.mono``."""
        return (
            f"* {{ font-family: {_css_family(cls.FAMILY)}; }}\n"
            f".mono {{ font-family: {_css_family(cls.FAMILY_MONO)}; }}\n"
        )


class Theme:
    """Main theme configuration."""

    fonts = Fonts
    tokens_file = TOKENS_FILE
    style_file = STYLE_FILE
