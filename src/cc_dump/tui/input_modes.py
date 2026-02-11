"""Pure mode system for key dispatch.

All keyboard input routes through on_key based on current mode.
Textual BINDINGS are not used - on_key is the sole dispatcher.

This module is RELOADABLE.
"""

from enum import Enum, auto


class InputMode(Enum):
    """Input modes - all on equal footing.

    No mode is privileged. Each has explicit keymap in MODE_KEYMAP.
    """
    NORMAL = auto()
    SEARCH_EDIT = auto()
    SEARCH_NAV = auto()


# [LAW:one-source-of-truth] Key→action mapping per mode.
# NORMAL: all app functionality
# SEARCH_NAV: navigation only (search keys handled specially in on_key)
# SEARCH_EDIT: empty (all keys consumed for text input)
MODE_KEYMAP: dict[InputMode, dict[str, str]] = {
    InputMode.NORMAL: {
        # Navigation
        "g": "go_top",
        "G": "go_bottom",
        "j": "scroll_down_line",
        "k": "scroll_up_line",
        "h": "scroll_left_col",
        "l": "scroll_right_col",
        "ctrl+f": "page_down",
        "ctrl+b": "page_up",
        "ctrl+d": "half_page_down",
        "ctrl+u": "half_page_up",

        # Visibility toggles (number keys)
        "1": "toggle_vis('headers')",
        "2": "toggle_vis('user')",
        "3": "toggle_vis('assistant')",
        "4": "toggle_vis('tools')",
        "5": "toggle_vis('system')",
        "6": "toggle_vis('budget')",
        "7": "toggle_vis('metadata')",

        # Detail toggles (shifted numbers - try both literal and descriptive names)
        "!": "toggle_detail('headers')",
        "exclamation_mark": "toggle_detail('headers')",
        "@": "toggle_detail('user')",
        "at": "toggle_detail('user')",
        "#": "toggle_detail('assistant')",
        "number_sign": "toggle_detail('assistant')",
        "$": "toggle_detail('tools')",
        "dollar_sign": "toggle_detail('tools')",
        "%": "toggle_detail('system')",
        "percent_sign": "toggle_detail('system')",
        "^": "toggle_detail('budget')",
        "circumflex_accent": "toggle_detail('budget')",
        "&": "toggle_detail('metadata')",
        "ampersand": "toggle_detail('metadata')",

        # Detail toggles (shifted letters - same as shifted numbers)
        "Q": "toggle_detail('headers')",
        "W": "toggle_detail('user')",
        "E": "toggle_detail('assistant')",
        "R": "toggle_detail('tools')",
        "T": "toggle_detail('system')",
        "Y": "toggle_detail('budget')",
        "U": "toggle_detail('metadata')",

        # Expand toggles (q-u for categories 1-7)
        "q": "toggle_expand('headers')",
        "w": "toggle_expand('user')",
        "e": "toggle_expand('assistant')",
        "r": "toggle_expand('tools')",
        "t": "toggle_expand('system')",
        "y": "toggle_expand('budget')",
        "u": "toggle_expand('metadata')",

        # Panels
        "8": "toggle_economics",
        "9": "toggle_timeline",
        "0": "toggle_follow",
        "*": "toggle_economics_breakdown",
        "ctrl+l": "toggle_logs",

        # Theme (try both key names - Textual might use descriptive names)
        "[": "prev_theme",
        "left_square_bracket": "prev_theme",
        "]": "next_theme",
        "right_square_bracket": "next_theme",
    },

    InputMode.SEARCH_NAV: {
        # Navigation only - search keys (n/N///escape/q/enter) handled specially
        "g": "go_top",
        "G": "go_bottom",
        "j": "scroll_down_line",
        "k": "scroll_up_line",
        "h": "scroll_left_col",
        "l": "scroll_right_col",
        "ctrl+f": "page_down",
        "ctrl+b": "page_up",
        "ctrl+d": "half_page_down",
        "ctrl+u": "half_page_up",
    },

    InputMode.SEARCH_EDIT: {
        # Empty - all keys handled specially for text input
    },
}


# [LAW:one-source-of-truth] Footer display per mode.
# Format: list of (key, description) tuples.
# These are shown in the custom footer based on current mode.
FOOTER_KEYS: dict[InputMode, list[tuple[str, str]]] = {
    InputMode.NORMAL: [
        ("1-7", "filters"),
        ("qwertyu", "expand"),
        ("QWERTYU", "detail"),
        ("8", "cost"),
        ("9", "timeline"),
        ("0", "follow"),
        ("[]", "theme"),
        ("/", "search"),
    ],
    InputMode.SEARCH_EDIT: [
        ("enter", "search"),
        ("esc", "keep"),
        ("q", "cancel"),
        ("alt+c/w/r/i", "modes"),
    ],
    InputMode.SEARCH_NAV: [
        ("n/N", "next/prev"),
        ("/", "edit"),
        ("esc", "keep"),
        ("q", "cancel"),
        ("jk", "scroll"),
    ],
}
