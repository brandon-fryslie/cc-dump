"""Pure mode system for key dispatch.

All keyboard input routes through on_key based on current mode.
Textual BINDINGS are not used - on_key is the sole dispatcher.

This module is RELOADABLE.
"""

from enum import Enum, auto


class InputMode(Enum):
    """Input modes derived from search state.

    Panel modes eliminated — Textual's focus-based Key event bubbling
    handles panel key dispatch naturally.
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
        # Navigation (printable — NORMAL only)
        "g": "go_top",
        "G": "go_bottom",
        "j": "scroll_down_line",
        "k": "scroll_up_line",
        "h": "scroll_left_col",
        "l": "scroll_right_col",

        # Visibility toggles (number keys) — 6 categories
        "1": "toggle_vis('user')",
        "2": "toggle_vis('assistant')",
        "3": "toggle_vis('tools')",
        "4": "toggle_vis('system')",
        "5": "toggle_vis('metadata')",
        "6": "toggle_vis('thinking')",

        # Detail toggles (shifted numbers - try both literal and descriptive names)
        "!": "toggle_detail('user')",
        "exclamation_mark": "toggle_detail('user')",
        "@": "toggle_detail('assistant')",
        "at": "toggle_detail('assistant')",
        "#": "toggle_detail('tools')",
        "number_sign": "toggle_detail('tools')",
        "$": "toggle_detail('system')",
        "dollar_sign": "toggle_detail('system')",
        "%": "toggle_detail('metadata')",
        "percent_sign": "toggle_detail('metadata')",
        "^": "toggle_detail('thinking')",
        "circumflex_accent": "toggle_detail('thinking')",

        # Detail toggles (shifted letters - same as shifted numbers)
        "Q": "toggle_detail('user')",
        "W": "toggle_detail('assistant')",
        "E": "toggle_detail('tools')",
        "R": "toggle_detail('system')",
        "T": "toggle_detail('metadata')",
        "Y": "toggle_detail('thinking')",

        # Expand toggles (q-y for categories 1-6)
        "q": "toggle_expand('user')",
        "w": "toggle_expand('assistant')",
        "e": "toggle_expand('tools')",
        "r": "toggle_expand('system')",
        "t": "toggle_expand('metadata')",
        "y": "toggle_expand('thinking')",

        # Panels (printable — NORMAL only)
        ".": "cycle_panel",
        "full_stop": "cycle_panel",
        ",": "cycle_panel_mode",
        "comma": "cycle_panel_mode",
        "tab": "cycle_panel_mode",
        "shift+tab": "cycle_panel_mode",
        "f": "toggle_follow",
        "alt+n": "next_special",
        "alt+p": "prev_special",

        # Info panel
        "i": "toggle_info",

        # Keys panel
        "?": "toggle_keys",
        "question_mark": "toggle_keys",

        # Tmux integration
        "c": "launch_tool",
        "z": "toggle_tmux_zoom",
        "Z": "toggle_auto_zoom",
        "L": "open_tmux_log_tail",

        # Filterset cycling (printable — NORMAL only)
        "=": "next_filterset",
        "equals_sign": "next_filterset",
        "-": "prev_filterset",
        "minus": "prev_filterset",

        # Settings panel
        "S": "toggle_settings",

        # Launch config panel
        "C": "toggle_launch_config",

        # Debug settings panel
        "D": "toggle_debug_settings",

        # Logs panel
        "ctrl+l": "toggle_logs",

        # Side channel (AI panel)
        "X": "toggle_side_channel",

        # Theme
        "[": "prev_theme",
        "left_square_bracket": "prev_theme",
        "]": "next_theme",
        "right_square_bracket": "next_theme",

        # Session navigation (within merged tab)
        "{": "prev_session",
        "left_curly_bracket": "prev_session",
        "}": "next_session",
        "right_curly_bracket": "next_session",
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
        ("1-6", "filters"),
        ("qwerty", "expand"),
        ("QWERTY", "detail"),
        (".", "panel"),
        ("tab/,", "mode"),
        ("f", "follow"),
        ("M-n/p", "special"),
        ("[]", "theme"),
        ("i", "info"),
        ("-=", "preset"),
        ("?", "keys"),
        ("/", "search"),
        ("c", "launch"),
        ("z", "zoom"),
        ("L", "tail"),
    ],
    InputMode.SEARCH_EDIT: [
        ("enter", "search"),
        ("^A/^E", "home/end"),
        ("^W", "del-word"),
        ("esc", "keep"),
        ("q", "cancel"),
        ("alt+c/w/r/i", "modes"),
    ],
    InputMode.SEARCH_NAV: [
        ("n/N", "next/prev"),
        ("^N/^P", "next/prev"),
        ("tab/S-tab", "next/prev"),
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
        ("1-6", "Toggle on/off"),
        ("Q-Y", "Detail level"),
        ("q-y", "Expand all"),
    ]),
    ("Panels", [
        (".", "Cycle panel"),
        ("tab/,", "Panel mode"),
        ("f", "Follow mode"),
        ("^L", "Debug logs"),
        ("i", "Server info"),
        ("?", "This panel"),
    ]),
    ("Search", [
        ("/", "Search"),
        ("=/-", "Next/prev preset"),
        ("M-n/M-p", "Special sections"),
        ("F1-9", "Load preset"),
    ]),
    ("Other", [
        ("[/]", "Cycle theme"),
        ("{/}", "Prev/next session"),
        ("c", "Launch tool (tmux)"),
        ("C", "Run configs"),
        ("D", "Debug"),
        ("z/Z", "Zoom (tmux)"),
        ("L", "Tail logs (tmux)"),
        ("S", "Settings"),
        ("D", "Debug"),
        ("X", "AI Workbench"),
        ("^C ^C", "Quit"),
    ]),
]
