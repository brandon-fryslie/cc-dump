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
        "1": "toggle_vis('user')",
        "2": "toggle_vis('assistant')",
        "3": "toggle_vis('tools')",
        "4": "toggle_vis('system')",
        "5": "toggle_vis('budget')",
        "6": "toggle_vis('metadata')",
        "7": "toggle_vis('headers')",

        # Detail toggles (shifted numbers - try both literal and descriptive names)
        "!": "toggle_detail('user')",
        "exclamation_mark": "toggle_detail('user')",
        "@": "toggle_detail('assistant')",
        "at": "toggle_detail('assistant')",
        "#": "toggle_detail('tools')",
        "number_sign": "toggle_detail('tools')",
        "$": "toggle_detail('system')",
        "dollar_sign": "toggle_detail('system')",
        "%": "toggle_detail('budget')",
        "percent_sign": "toggle_detail('budget')",
        "^": "toggle_detail('metadata')",
        "circumflex_accent": "toggle_detail('metadata')",
        "&": "toggle_detail('headers')",
        "ampersand": "toggle_detail('headers')",

        # Detail toggles (shifted letters - same as shifted numbers)
        "Q": "toggle_detail('user')",
        "W": "toggle_detail('assistant')",
        "E": "toggle_detail('tools')",
        "R": "toggle_detail('system')",
        "T": "toggle_detail('budget')",
        "Y": "toggle_detail('metadata')",
        "U": "toggle_detail('headers')",

        # Expand toggles (q-u for categories 1-7)
        "q": "toggle_expand('user')",
        "w": "toggle_expand('assistant')",
        "e": "toggle_expand('tools')",
        "r": "toggle_expand('system')",
        "t": "toggle_expand('budget')",
        "y": "toggle_expand('metadata')",
        "u": "toggle_expand('headers')",

        # Panels
        ".": "cycle_panel",
        "full_stop": "cycle_panel",
        ",": "cycle_panel_mode",
        "comma": "cycle_panel_mode",
        "0": "toggle_follow",
        "ctrl+l": "toggle_logs",

        # Info panel
        "i": "toggle_info",

        # Keys panel
        "?": "toggle_keys",
        "question_mark": "toggle_keys",

        # Tmux integration
        "c": "launch_claude",
        "z": "toggle_tmux_zoom",
        "Z": "toggle_auto_zoom",

        # Filterset cycling
        "=": "next_filterset",
        "equals_sign": "next_filterset",
        "-": "prev_filterset",
        "minus": "prev_filterset",

        # Filterset presets (F-key apply, Shift+F-key save; F3 broken, skip it)
        "f1": "apply_filterset('1')",
        "f2": "apply_filterset('2')",
        "f4": "apply_filterset('4')",
        "f5": "apply_filterset('5')",
        "f6": "apply_filterset('6')",
        "f7": "apply_filterset('7')",
        "f8": "apply_filterset('8')",
        "f9": "apply_filterset('9')",
        "shift+f1": "save_filterset('1')",
        "shift+f2": "save_filterset('2')",
        "shift+f4": "save_filterset('4')",
        "shift+f5": "save_filterset('5')",
        "shift+f6": "save_filterset('6')",
        "shift+f7": "save_filterset('7')",
        "shift+f8": "save_filterset('8')",
        "shift+f9": "save_filterset('9')",

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
        (".", "panel"),
        (",", "mode"),
        ("0", "follow"),
        ("[]", "theme"),
        ("i", "info"),
        ("-=", "preset"),
        ("?", "keys"),
        ("/", "search"),
        ("c", "claude"),
        ("z", "zoom"),
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


# [LAW:one-source-of-truth] Display data for keys panel.
# Format: list of (group_title, [(key_display, description), ...]) tuples.
KEY_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Nav", [
        ("g/G", "Top / bottom"),
        ("j/k", "Line up / down"),
        ("h/l", "Column L / R"),
        ("^D/^U", "Half page"),
        ("^F/^B", "Full page"),
    ]),
    ("Categories", [
        ("1-7", "Toggle on/off"),
        ("Q-U", "Detail level"),
        ("q-u", "Expand all"),
    ]),
    ("Panels", [
        (".", "Cycle panel"),
        (",", "Panel mode"),
        ("0", "Follow mode"),
        ("^L", "Debug logs"),
        ("i", "Server info"),
        ("?", "This panel"),
    ]),
    ("Search", [
        ("/", "Search"),
        ("=/-", "Next/prev preset"),
        ("F1-9", "Load preset"),
        ("S+F1-9", "Save preset"),
    ]),
    ("Other", [
        ("[/]", "Cycle theme"),
        ("c", "Claude (tmux)"),
        ("z/Z", "Zoom (tmux)"),
    ]),
]
