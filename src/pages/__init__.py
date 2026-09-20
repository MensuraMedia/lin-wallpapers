"""Pages: one ``BasePage`` subclass per route. GTK only — no filesystem, no providers.

The view models are injected through :class:`PageContext`, whose fields are deliberately typed ``Any``:
pages must not import a view-model (or catalogue) type, so the composition root (``src/main.py``) fills
this context and the pages read it duck-typed. ``PageContext`` also carries the browse enum *classes*
so a page can call ``browse_vm.set_segment(context.segment.IDEAL)`` without importing them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .page_about import AboutPage
from .page_base import BasePage
from .page_browse import BrowsePage
from .page_collections import CollectionsPage
from .page_history import HistoryPage
from .page_image import ImagePage
from .page_preview import PreviewPage
from .page_screens import ScreensPage
from .page_settings import SettingsPage
from .page_sources import SourcesPage
from .page_test import TestPage

# Sidebar routes, in order (Ctrl+1…9), then the pages reached from elsewhere.
SIDEBAR_PAGES: tuple[type[BasePage], ...] = (
    BrowsePage,
    ImagePage,
    ScreensPage,
    PreviewPage,
    SourcesPage,
    CollectionsPage,
    HistoryPage,
    SettingsPage,
    TestPage,
)
OTHER_PAGES: tuple[type[BasePage], ...] = (AboutPage,)
ALL_PAGES = SIDEBAR_PAGES + OTHER_PAGES


@dataclass(frozen=True)
class PageContext:
    """The view models and browse enum classes the pages bind to, kept opaque (see the module docstring)."""

    scan_vm: Any = None
    sources_vm: Any = None
    browse_vm: Any = None
    test_vm: Any = None
    segment: Any = None
    orientation: Any = None
    aspect: Any = None
    sort: Any = None


def make_page(page_class: type[BasePage], context: PageContext | None) -> BasePage:
    """Instantiate a page, injecting the context only into the pages that ask for it (``wants_context``)."""
    if getattr(page_class, "wants_context", False):
        return page_class(context=context)  # type: ignore[call-arg]
    return page_class()


__all__ = ["ALL_PAGES", "OTHER_PAGES", "SIDEBAR_PAGES", "BasePage", "PageContext", "make_page"]
