"""Custom Footer widget with data-driven rendering."""

from rich.text import Text
from textual.widgets import Static

import cc_dump.palette


class StatusFooter(Static):
    """Data-driven footer. No private Textual API imports.

    // [LAW:dataflow-not-control-flow] Render pipeline is fixed; data determines style.
    // [LAW:single-enforcer] update_display() is the sole render entry.
    // [LAW:one-source-of-truth] Icons from _LEVEL_EXPANDED_ICONS, colors from palette.
    """

    # Icon encodes level AND expansion state
    _LEVEL_EXPANDED_ICONS = {
        (1, False): "\u00b7",  # ·  Existence
        (1, True): "\u00b7",  # ·  Existence (same — no expansion at existence)
        (2, False): "\u25b7",  # ▷  Summary Collapsed
        (2, True): "\u25bd",  # ▽  Summary Expanded
        (3, False): "\u25b6",  # ▶  Full Collapsed
        (3, True): "\u25bc",  # ▼  Full Expanded
    }

    _CATEGORY_ITEMS = [
        ("1", "headers"),
        ("2", "user"),
        ("3", "assistant"),
        ("4", "tools"),
        ("5", "system"),
        ("6", "budget"),
        ("7", "metadata"),
    ]

    _ACTION_ITEMS = [
        ("8", "cost", "economics"),
        ("9", "timeline", "timeline"),
    ]

    _COMMAND_ITEMS = [("/", "search"), ("q", "quit")]

    def update_display(self, state: dict) -> None:
        """Render footer from state. Called by app._update_footer_state()."""
        self.update(self._render_footer(state))

    def _render_footer(self, state: dict) -> Text:
        """Build 2-line Rich Text — categories on line 1, actions on line 2."""
        p = cc_dump.palette.PALETTE

        # Line 1: categories with icon+color
        line1 = Text()
        for key, name in self._CATEGORY_ITEMS:
            value = state.get(name, (1, False))
            level, expanded = value if isinstance(value, tuple) else (1, False)
            icon = self._LEVEL_EXPANDED_ICONS.get((level, expanded), "\u00b7")
            color = p.filter_color(name)
            style = f"bold {color}" if level > 1 else "dim"
            if line1.plain:
                line1.append("  ")
            line1.append(f" {key} ", style="bold" if level > 1 else "dim")
            line1.append(icon, style=style)
            line1.append(name, style=style)

        # Line 2: actions + follow + commands
        line2 = Text()
        for key, label, state_key in self._ACTION_ITEMS:
            is_active = bool(state.get(state_key, False))
            color = p.filter_color(state_key)
            style = f"bold {color}" if is_active else "dim"
            if line2.plain:
                line2.append("  ")
            line2.append(f" {key}", style="bold" if is_active else "dim")
            line2.append(" ")
            line2.append(label, style=style)

        # Follow mode — prominent when active
        follow_active = bool(state.get("follow", False))
        line2.append("  ")
        if follow_active:
            line2.append(" 0", style="bold")
            line2.append(" ")
            line2.append("FOLLOW", style="bold reverse green")
        else:
            line2.append(" 0", style="dim")
            line2.append(" ")
            line2.append("follow", style="dim")

        for key, label in self._COMMAND_ITEMS:
            line2.append("  ")
            line2.append(f" {key}", style="bold")
            line2.append(" ")
            line2.append(label, style="")

        return Text("\n").join([line1, line2])
