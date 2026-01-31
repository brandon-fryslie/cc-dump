"""Terminal color constants.

ANSI formatting escapes and palette-derived 24-bit color escapes.
"""

import cc_dump.palette

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"


def _fg24(hex_color: str) -> str:
    """Convert #RRGGBB to 24-bit ANSI foreground escape."""
    r, g, b = cc_dump.palette._hex_to_rgb(hex_color)
    return f"\033[38;2;{r};{g};{b}m"


def _bg24(hex_color: str) -> str:
    """Convert #RRGGBB to 24-bit ANSI background escape."""
    r, g, b = cc_dump.palette._hex_to_rgb(hex_color)
    return f"\033[48;2;{r};{g};{b}m"


def _build_tag_colors() -> list[tuple[str, str]]:
    """Build TAG_COLORS from palette: (fg_escape, bg_escape) pairs."""
    p = cc_dump.palette.PALETTE
    result = []
    for i in range(min(p.count, 12)):
        fg_hex, bg_hex = p.fg_on_bg(i)
        result.append((_fg24(fg_hex), _bg24(bg_hex)))
    return result


TAG_COLORS = _build_tag_colors()

SEPARATOR = DIM + "\u2500" * 70 + RESET
THIN_SEP = DIM + "\u2504" * 40 + RESET
