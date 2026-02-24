"""Error indicator overlay for ConversationView.

Pure rendering module — no widget class. ConversationView composites
indicator strips onto conversation output in render_line().

// [LAW:locality-or-seam] All indicator logic lives here. ConversationView
//   calls composite_overlay() and hit_test_event() at exactly 2 points.
// [LAW:one-source-of-truth] IndicatorState is the sole state for error items.

RELOADABLE — pure data + rendering, no live state.
"""

from collections import namedtuple

from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.strip import Strip

import cc_dump.tui.rendering


ErrorItem = namedtuple("ErrorItem", ["id", "icon", "summary"])

# Visual constants
_COLLAPSED_ICON = " \u274c "  # " ❌ "
_COLLAPSED_WIDTH = 4  # cell width of collapsed indicator
_PADDING = 1  # right-side padding cell

def _contrast_text(bg_hex: str, light_hex: str, dark_hex: str) -> str:
    """Pick light/dark foreground based on background luminance."""
    try:
        color = Color.parse(bg_hex)
        r, g, b = color.rgb
        # Standard relative luminance approximation.
        luminance = (0.2126 * (r / 255.0)) + (0.7152 * (g / 255.0)) + (0.0722 * (b / 255.0))
        return dark_hex if luminance >= 0.53 else light_hex
    except Exception:
        return light_hex


def _indicator_styles() -> tuple[Style, Style]:
    """Build (header_style, body_style) from current active theme.

    // [LAW:one-source-of-truth] Indicator colors derive from rendering theme state.
    """
    try:
        tc = cc_dump.tui.rendering.get_theme_colors()
        header_bg = tc.error
        header_fg = _contrast_text(header_bg, tc.background, tc.foreground)
        body_bg = tc.surface
        body_fg = tc.error
        header_style = Style(color=header_fg, bgcolor=header_bg, bold=True)
        body_style = Style(color=body_fg, bgcolor=body_bg)
        return (header_style, body_style)
    except Exception:
        # Theme may not be initialized in isolated tests; keep deterministic fallback.
        return (
            Style(color="#FFFFFF", bgcolor="#BA3C5B", bold=True),
            Style(color="#BA3C5B", bgcolor="#2B2B2B"),
        )


class IndicatorState:
    """Mutable state for the error indicator overlay."""

    __slots__ = ("items", "expanded")

    def __init__(self):
        self.items: list[ErrorItem] = []
        self.expanded: bool = False

    def height(self) -> int:
        """How many viewport lines the indicator occupies."""
        if not self.items:
            return 0
        if not self.expanded:
            return 1
        return 1 + len(self.items)

    def width(self) -> int:
        """Cell width of the indicator."""
        if not self.items:
            return 0
        if not self.expanded:
            return _COLLAPSED_WIDTH + _PADDING
        # Expanded: max of header and detail lines
        header = _render_header(self.items[0])
        detail_widths = [len(f"    {item.summary} ") for item in self.items]
        return max(len(header), *detail_widths) + _PADDING

    def render_strips(self) -> list[Strip]:
        """Render indicator as list of Strips (one per viewport line)."""
        if not self.items:
            return []

        header_style, body_style = _indicator_styles()

        if not self.expanded:
            text = _COLLAPSED_ICON
            segments = [Segment(text, header_style), Segment(" ")]
            return [Strip(segments)]

        # Expanded: header + detail lines
        w = self.width()
        strips = []

        # Header line: icon + summary of first item
        header_text = _render_header(self.items[0])
        padded = header_text.ljust(w - _PADDING)
        strips.append(Strip([Segment(padded, header_style), Segment(" ")]))

        # Detail lines
        for item in self.items:
            detail = f"    {item.summary} "
            padded = detail.ljust(w - _PADDING)
            strips.append(Strip([Segment(padded, body_style), Segment(" ")]))

        return strips


def _render_header(item: ErrorItem) -> str:
    """Render the header line text for an error item."""
    return f" {item.icon} restart needed "


def composite_overlay(strip: Strip, viewport_y: int, width: int, indicator: IndicatorState) -> Strip:
    """Composite indicator strips onto a conversation strip.

    // [LAW:dataflow-not-control-flow] Always called; no-op when no items.

    Args:
        strip: The conversation content strip for this viewport line.
        viewport_y: Viewport-relative line index (0 = top of viewport).
        width: Viewport width in cells.
        indicator: Current indicator state.

    Returns:
        Strip with indicator composited in upper-right, or original strip unchanged.
    """
    ind_height = indicator.height()
    if ind_height == 0 or viewport_y >= ind_height:
        return strip

    ind_strips = indicator.render_strips()
    if viewport_y >= len(ind_strips):
        return strip

    overlay = ind_strips[viewport_y]
    ind_width = indicator.width()

    # Crop conversation content to make room, then append overlay
    content_width = width - ind_width
    if content_width < 0:
        content_width = 0

    cropped = strip.crop_extend(0, content_width, Style())
    # Combine: cropped conversation + overlay
    combined_segments = list(cropped._segments) + list(overlay._segments)
    return Strip(combined_segments, width)


def hit_test_event(indicator: IndicatorState, event_x: int, event_y: int, viewport_width: int) -> bool:
    """Test if a mouse event coordinate is within the indicator region.

    Args:
        indicator: Current indicator state.
        event_x: Widget-relative x coordinate from mouse event.
        event_y: Widget-relative y coordinate (viewport-relative).
        viewport_width: Width of the viewport in cells.

    Returns:
        True if the coordinate is within the indicator bounds.
    """
    ind_height = indicator.height()
    if ind_height == 0:
        return False

    # Vertical: must be within indicator rows
    if event_y >= ind_height:
        return False

    # Horizontal: must be in the right portion where indicator is drawn
    ind_width = indicator.width()
    left_edge = viewport_width - ind_width
    return event_x >= left_edge
