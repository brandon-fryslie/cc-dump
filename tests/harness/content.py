"""Text extraction from Textual strips and widgets.

Uses strip._segments (private API) for plain text extraction.
Acceptable for test utilities; fragile across Textual major versions.
"""

from rich.text import Text
from textual.strip import Strip

from cc_dump.tui.app import CcDumpApp


def strips_to_text(strips: list[Strip]) -> str:
    """Extract plain text from a list of Strip objects.

    NOTE: Uses strip._segments (private Textual API).
    """
    return "".join(seg.text for strip in strips for seg in strip._segments)


def turn_text(app: CcDumpApp, turn_index: int) -> str:
    """Get the rendered text content of a specific turn."""
    conv = app._get_conv()
    if conv is not None and turn_index < len(conv._turns):
        return strips_to_text(conv._turns[turn_index].strips)
    return ""


def all_turns_text(app: CcDumpApp) -> str:
    """Get all rendered turn text concatenated."""
    conv = app._get_conv()
    if conv is None:
        return ""
    return "".join(strips_to_text(td.strips) for td in conv._turns)


def widget_text(app: CcDumpApp, selector: str) -> str:
    """Get plain text content from a Static widget by CSS selector."""
    try:
        widget = app.query_one(selector)
        renderable = widget.render()
        if isinstance(renderable, Text):
            return renderable.plain
        return str(renderable)
    except Exception:
        return ""
