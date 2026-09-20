"""Pages: one ``BasePage`` subclass per route. GTK only — no filesystem, no providers."""

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

# Sidebar routes, in order (Ctrl+1…8), then the pages reached from elsewhere.
SIDEBAR_PAGES: tuple[type[BasePage], ...] = (
    BrowsePage,
    ImagePage,
    ScreensPage,
    PreviewPage,
    SourcesPage,
    CollectionsPage,
    HistoryPage,
    SettingsPage,
)
OTHER_PAGES: tuple[type[BasePage], ...] = (AboutPage,)
ALL_PAGES = SIDEBAR_PAGES + OTHER_PAGES

__all__ = ["ALL_PAGES", "OTHER_PAGES", "SIDEBAR_PAGES", "BasePage"]
