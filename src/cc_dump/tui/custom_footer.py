"""Custom Footer widget with data-driven rendering."""

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

import cc_dump.tui.rendering
from cc_dump.formatting import VisState, HIDDEN


def _click(action: str) -> Style:
    """Create a Style with @click meta for Textual action dispatch."""
    return Style.from_meta({"@click": action})


class StatusFooter(Static):
    """Data-driven footer. No private Textual API imports.

    // [LAW:dataflow-not-control-flow] Render pipeline is fixed; data determines style.
    // [LAW:single-enforcer] update_display() is the sole render entry.
    // [LAW:one-source-of-truth] Icons from _VIS_ICONS, colors from palette.
    """

    ALLOW_SELECT = False

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

    # [LAW:one-source-of-truth] Panel names and display labels for cycling indicator
    _PANEL_ITEMS = [
        ("stats", "stats"),
        ("economics", "cost"),
        ("timeline", "timeline"),
    ]

    _COMMAND_ITEMS = [("/", "search")]

    def update_display(self, state: dict) -> None:
        """Render footer from state. Called by app._update_footer_state()."""
        self.update(self._render_footer(state))

    def _render_footer(self, state: dict) -> Text:
        """Build 2-line Rich Text — categories on line 1, actions on line 2.

        // [LAW:dataflow-not-control-flow] State values determine rendering, no branching.
        Each span carries @click meta so clicks dispatch the matching action.
        """
        tc = cc_dump.tui.rendering.get_theme_colors()

        # Line 1: categories with icon+color — active gets colored background
        # no_wrap=True prevents mid-chip line breaks
        line1 = Text(no_wrap=True)
        for key, name in self._CATEGORY_ITEMS:
            vis = state.get(name, HIDDEN)
            icon = self._VIS_ICONS[vis]
            _, bg_color, fg_light = tc.filter_colors[name]
            # // [LAW:dataflow-not-control-flow] Style derived from vis.visible value
            active_style = f"bold {fg_light} on {bg_color}"
            style = active_style if vis.visible else "dim"
            click = _click(f"app.cycle_vis('{name}')")
            # [LAW:one-type-per-behavior] Single segment = single hover region for unified chip
            line1.append(f" {key} {name} {icon} ", style=Style.parse(style) + click)

        # Line 2: panel indicator + follow + commands
        line2 = Text(no_wrap=True)
        active_panel = state.get("active_panel", "stats")
        click = _click("app.cycle_panel")
        for i, (panel_name, label) in enumerate(self._PANEL_ITEMS):
            is_active = (panel_name == active_panel)
            # // [LAW:dataflow-not-control-flow] Style derived from is_active value
            color = tc.action_colors[i % len(tc.action_colors)]
            active_style = f"bold {color} reverse"
            style = active_style if is_active else "dim"
            if line2.plain:
                line2.append("  ")
            line2.append(f" {label} ", style=Style.parse(style) + click)

        # Follow mode — prominent when active
        follow_active = bool(state.get("follow", False))
        follow_click = _click("app.toggle_follow")
        line2.append("  ")
        if follow_active:
            line2.append(" 0", style=Style.parse("bold") + follow_click)
            line2.append(" ", style=follow_click)
            tc = cc_dump.tui.rendering.get_theme_colors()
            line2.append("FOLLOW", style=Style.parse(tc.follow_active_style) + follow_click)
        else:
            line2.append(" 0", style=Style.parse("dim") + follow_click)
            line2.append(" ", style=follow_click)
            line2.append("follow", style=Style.parse("dim") + follow_click)

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

        # Tmux indicators — only shown when tmux is available
        # // [LAW:dataflow-not-control-flow] Always run; style varies by state values.
        tmux_available = state.get("tmux_available", False)
        tmux_auto = state.get("tmux_auto_zoom", False)
        tmux_zoomed = state.get("tmux_zoomed", False)
        if tmux_available:
            line2.append("  ")
            claude_click = _click("app.launch_claude")
            line2.append(" c", style=Style.parse("bold") + claude_click)
            line2.append(" ", style=claude_click)
            line2.append("claude", style=Style.parse("") + claude_click)

            zoom_click = _click("app.toggle_tmux_zoom")
            line2.append("  ")
            zoom_style = "bold reverse" if tmux_zoomed else "dim"
            line2.append(" z", style=Style.parse("bold" if tmux_zoomed else "dim") + zoom_click)
            line2.append(" ", style=zoom_click)
            line2.append("zoom", style=Style.parse(zoom_style) + zoom_click)

            auto_click = _click("app.toggle_auto_zoom")
            line2.append("  ")
            auto_style = "bold reverse" if tmux_auto else "dim"
            line2.append(" Z", style=Style.parse("bold" if tmux_auto else "dim") + auto_click)
            line2.append(" ", style=auto_click)
            line2.append("auto", style=Style.parse(auto_style) + auto_click)

        return Text("\n").join([line1, line2])
