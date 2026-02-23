"""Pure data constants for action handlers — hot-reloadable.

// [LAW:one-source-of-truth] Canonical definitions for visibility cycling,
// filterset naming, and panel toggle configuration.
// [LAW:one-way-deps] Depends on formatting (VisState). No upward deps.

Extracted from action_handlers.py so that tweaking these values
(e.g. adding a filterset, reordering the visibility cycle) takes
effect immediately via hot-reload without restart.
"""

import cc_dump.core.formatting

# [LAW:one-source-of-truth] Ordered slot list for cycling (skips F3)
FILTERSET_SLOTS = ["1", "2", "4", "5", "6", "7", "8", "9"]

# [LAW:one-source-of-truth] Names for built-in filterset slots
FILTERSET_NAMES: dict[str, str] = {
    "1": "Conversation",
    "2": "Overview",
    "4": "Tools",
    "5": "System",
    "6": "Cost",
    "7": "Full Debug",
    "8": "Assistant",
    "9": "Minimal",
}

# [LAW:one-source-of-truth] Ordered visibility states for cycling filter chips.
# Progression: hidden → summary collapsed → summary expanded → full collapsed → full expanded
VIS_CYCLE = [
    cc_dump.core.formatting.VisState(False, False, False),  # 1. Hidden
    cc_dump.core.formatting.VisState(True, False, False),   # 2. Summary Collapsed
    cc_dump.core.formatting.VisState(True, False, True),    # 3. Summary Expanded
    cc_dump.core.formatting.VisState(True, True, False),    # 4. Full Collapsed
    cc_dump.core.formatting.VisState(True, True, True),     # 5. Full Expanded
]

# [LAW:dataflow-not-control-flow] Visibility toggle specs — data, not branches.
# Each tuple: (store_key_prefix, force_value_or_None) where None means "toggle".
VIS_TOGGLE_SPECS = {
    "vis": [("vis", None)],
    "detail": [("vis", True), ("full", None)],
    "expand": [("vis", True), ("exp", None)],
}

# [LAW:one-type-per-behavior] Toggle config for non-cycling panels
PANEL_TOGGLE_CONFIG = {
    "logs": ("show_logs", "_get_logs", None),
    "info": ("show_info", "_get_info", None),
}
