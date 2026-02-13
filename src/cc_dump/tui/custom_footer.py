"""Custom Footer widget with data-driven rendering."""

from rich.text import Text
from textual.widgets import Static

import cc_dump.palette
import cc_dump.tui.rendering
from cc_dump.formatting import VisState, HIDDEN


class StatusFooter(Static):
    """Data-driven footer. No private Textual API imports.

    // [LAW:dataflow-not-control-flow] Render pipeline is fixed; data determines style.
    // [LAW:single-enforcer] update_display() is the sole render entry.
    // [LAW:one-source-of-truth] Icons from _VIS_ICONS, colors from palette.
    """

    # Icon encodes visibility state (5 states)
    _VIS_ICONS: dict[VisState, str] = {
        # Hidden states
        VisState(False, False, False): "\u00b7",  # ·  Hidden
        VisState(False, False, True):  "\u00b7",  # ·  Hidden
        VisState(False, True, False):  "\u00b7",  # ·  Hidden
        VisState(False, True, True):   "\u00b7",  # ·  Hidden
        # Summary level
        VisState(True, False, False):  "\u25b7",  # ▷  Summary Collapsed
        VisState(True, False, True):   "\u25bd",  # ▽  Summary Expanded
        # Full level
        VisState(True, True, False):   "\u25b6",  # ▶  Full Collapsed
        VisState(True, True, True):    "\u25bc",  # ▼  Full Expanded
    }

    _CATEGORY_ITEMS = [
        ("1", "user"),
        ("2", "assistant"),
        ("3", "tools"),
        ("4", "system"),
        ("5", "budget"),
        ("6", "metadata"),
        ("7", "headers"),
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
        """Build 2-line Rich Text — categories on line 1, actions on line 2.

        // [LAW:dataflow-not-control-flow] State values determine rendering, no branching.
        """
        p = cc_dump.palette.PALETTE

        # Line 1: categories with icon+color — active gets colored background
        # no_wrap=True prevents mid-chip line breaks
        line1 = Text(no_wrap=True)
        for key, name in self._CATEGORY_ITEMS:
            vis = state.get(name, HIDDEN)
            icon = self._VIS_ICONS[vis]
            fg_light = p.filter_fg_light(name)
            bg_color = p.filter_bg(name)
            # // [LAW:dataflow-not-control-flow] Style derived from vis.visible value
            active_style = f"bold {fg_light} on {bg_color}"
            style = active_style if vis.visible else "dim"
            line1.append(f" {key} ", style=active_style if vis.visible else "dim")
            line1.append(name, style=style)
            line1.append(f" {icon} ", style=style)

        # Line 2: actions + follow + commands
        line2 = Text(no_wrap=True)
        for key, label, state_key in self._ACTION_ITEMS:
            is_active = bool(state.get(state_key, False))
            fg_light = p.filter_fg_light(state_key)
            bg_color = p.filter_bg(state_key)
            # // [LAW:dataflow-not-control-flow] Style derived from is_active value
            active_style = f"bold {fg_light} on {bg_color}"
            style = active_style if is_active else "dim"
            if line2.plain:
                line2.append("  ")
            line2.append(f" {key}", style=active_style if is_active else "dim")
            line2.append(" ")
            line2.append(label, style=style)

        # Follow mode — prominent when active
        follow_active = bool(state.get("follow", False))
        line2.append("  ")
        if follow_active:
            line2.append(" 0", style="bold")
            line2.append(" ")
            tc = cc_dump.tui.rendering.get_theme_colors()
            line2.append("FOLLOW", style=tc.follow_active_style)
        else:
            line2.append(" 0", style="dim")
            line2.append(" ")
            line2.append("follow", style="dim")

        for key, label in self._COMMAND_ITEMS:
            line2.append("  ")
            line2.append(f" {key}", style="bold")
            line2.append(" ")
            line2.append(label, style="")

        # Filterset indicator — show active preset slot
        active_slot = state.get("active_filterset")
        # [LAW:dataflow-not-control-flow] Always append; style varies by value.
        line2.append("  ")
        if active_slot is not None:
            tc = cc_dump.tui.rendering.get_theme_colors()
            line2.append(f" F{active_slot} ", style=tc.follow_active_style)
        else:
            line2.append(" F- ", style="dim")

        return Text("\n").join([line1, line2])
