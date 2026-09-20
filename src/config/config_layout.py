"""Layout constants: the 8 px grid and the 12/16 px radii (TECHNICAL-CONCEPT §14, §16)."""


class Dimensions:
    """Window and shell dimensions."""

    WINDOW_DEFAULT_WIDTH = 1280
    WINDOW_DEFAULT_HEIGHT = 800
    WINDOW_MIN_WIDTH = 960
    WINDOW_MIN_HEIGHT = 640

    SIDEBAR_WIDTH = 150  # the starter template's width
    LOGO_SIZE = 46
    LOGO_RADIUS = 14
    LOGO_GLYPH_SIZE = 26
    NAV_ICON_SIZE = 14
    NAV_BUTTON_HEIGHT = 28  # mirrored by .nav-button min-height in style.css

    CONTENT_MARGIN = 24  # left / right of the page
    CONTENT_MARGIN_TOP = 20  # top / bottom of the page


class Spacing:
    """Multiples of the 8 px grid."""

    GRID = 8
    NONE = 0
    HAIR = 1  # logo name → tagline
    NAV_GAP = 2  # between sidebar route buttons
    HEADER_GAP = 3  # page title → subtitle
    XSMALL = 4
    PANEL_GAP = 6  # lines of the "this machine" panel
    SMALL = 8
    LOGO_GAP = 10  # logo tile → name
    PAGE_GAP = 14  # page header → first card, and between cards
    MEDIUM = 16
    SIDEBAR_GAP = 18  # between sidebar sections
    LARGE = 24
    XLARGE = 32


class Radius:
    """Corner radii, mirrored by the component classes in style.css."""

    CONTROL = 12
    CARD = 16


class Layout:
    """Main layout configuration."""

    dimensions = Dimensions
    spacing = Spacing
    radius = Radius
