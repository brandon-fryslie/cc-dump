"""Custom Footer widget with composed Textual widgets."""

from textual.color import Color
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static

import cc_dump.tui.rendering
import cc_dump.tui.widget_factory
import cc_dump.io.logging_setup
from cc_dump.core.formatting import VisState, HIDDEN
from cc_dump.tui.chip import Chip


class StatusFooter(Widget):
    """Data-driven footer built from composed widgets.

    // [LAW:dataflow-not-control-flow] Render pipeline is fixed; data determines style.
    // [LAW:single-enforcer] update_display() is the sole render entry.
    // [LAW:one-source-of-truth] Icons from _VIS_ICONS, colors from palette.
    """

    ALLOW_SELECT = False

    DEFAULT_CSS = """
    StatusFooter {
        dock: bottom;
        height: auto;
        max-height: 3;
        padding: 0 1;
        layout: vertical;
    }

    StatusFooter Horizontal {
        height: 1;
        width: 100%;
    }

    StatusFooter Chip {
        width: auto;
        height: 1;
        text-style: bold;
    }

    StatusFooter Chip:hover {
        opacity: 0.8;
    }

    /* Hidden chips: dim, but still respond to hover */
    StatusFooter Chip.-hidden {
        text-style: initial;
        opacity: 0.5;
    }

    StatusFooter Chip.-hidden:hover {
        opacity: 0.7;
    }

    /* Dim chips (follow off, zoom/auto off): same hover pattern */
    StatusFooter Chip.-dim {
        opacity: 0.5;
    }

    StatusFooter Chip.-dim:hover {
        opacity: 0.7;
    }

    StatusFooter Static {
        width: auto;
        height: 1;
    }

    StatusFooter .tmux {
        display: none;
    }

    StatusFooter .tmux.-available {
        display: block;
    }
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
        ("5", "metadata"),
        ("6", "thinking"),
    ]

    def compose(self):
        # Line 1: category chips
        with Horizontal(id="footer-categories"):
            for key, name in self._CATEGORY_ITEMS:
                yield Chip(
                    f" {key} {name} \u00b7 ",
                    action=f"app.cycle_vis('{name}')",
                    id=f"cat-{name}",
                )
        # Line 2: command row
        with Horizontal(id="footer-commands"):
            yield Chip(
                " / search ",
                action="app.simulate_key('/')",
                id="cmd-search",
            )
            yield Chip(
                " f FOLLOW ",
                action="app.toggle_follow",
                id="cmd-follow",
            )
            yield Static(" F- ", id="cmd-filterset")
            yield Chip(
                " c launch ",
                action="app.launch_tool",
                id="cmd-launch-tool",
                classes="tmux",
            )
            yield Chip(
                " z zoom ",
                action="app.toggle_tmux_zoom",
                id="cmd-zoom",
                classes="tmux",
            )
            yield Chip(
                " Z auto ",
                action="app.toggle_auto_zoom",
                id="cmd-auto-zoom",
                classes="tmux",
            )
            yield Chip(
                " L tail ",
                action="app.open_tmux_log_tail",
                id="cmd-tail-log",
                classes="tmux",
            )
        # Line 3: log file path (static — set once on mount)
        runtime = cc_dump.io.logging_setup.get_runtime()
        log_path = runtime.file_path if runtime is not None else ""
        yield Chip(
            f" log: {log_path} " if log_path else " log: (unavailable) ",
            action="app.copy_log_path" if log_path else None,
            id="footer-log",
        )

    def update_display(self, state: dict) -> None:
        """Render footer from state dict. Called by footer_state reaction.

        // [LAW:dataflow-not-control-flow] State values determine rendering, no branching.
        """
        tc = cc_dump.tui.rendering.get_theme_colors()

        # Line 1: category chips — icon + color from state
        for key, name in self._CATEGORY_ITEMS:
            chip = self.query_one(f"#cat-{name}", Chip)
            vis = state.get(name, HIDDEN)
            icon = self._VIS_ICONS[vis]
            chip.update(f" {key} {name} {icon} ")

            _, bg_hex, fg_hex = tc.filter_colors[name]
            # // [LAW:dataflow-not-control-flow] Style derived from vis.visible value
            # Colors always set; CSS class -hidden dims via opacity.
            chip.set_class(not vis.visible, "-hidden")
            chip.styles.background = Color.parse(bg_hex)
            chip.styles.color = Color.parse(fg_hex)

        # Line 2: follow chip — 3-state
        # // [LAW:dataflow-not-control-flow] Style + label derived from follow_state via table.
        FollowState = cc_dump.tui.widget_factory.FollowState
        follow_state = state.get("follow_state", FollowState.ACTIVE)
        follow_chip = self.query_one("#cmd-follow", Chip)

        bg_color = Color.parse(tc.background)
        fg_color = Color.parse(tc.foreground)
        # [LAW:dataflow-not-control-flow] Table lookup, not branches.
        _FOLLOW_DISPLAY: dict = {
            FollowState.OFF: (" f off ", True, bg_color, fg_color),
            FollowState.ENGAGED: (" f follow ", False, fg_color, bg_color),
            FollowState.ACTIVE: (" f FOLLOW ", False, bg_color, fg_color),
        }
        label, is_dim, follow_bg, follow_fg = _FOLLOW_DISPLAY[follow_state]
        follow_chip.update(label)
        follow_chip.set_class(is_dim, "-dim")
        follow_chip.styles.background = follow_bg
        follow_chip.styles.color = follow_fg

        # Filterset indicator
        # [LAW:dataflow-not-control-flow] Always update; style varies by value.
        active_slot = state.get("active_filterset")
        filterset_label = self.query_one("#cmd-filterset", Static)
        filterset_label.update(
            f" F{active_slot} " if active_slot is not None else " F- "
        )
        # [LAW:dataflow-not-control-flow] Always set; values vary by state.
        has_filterset = active_slot is not None
        filterset_label.styles.background = bg_color if has_filterset else fg_color
        filterset_label.styles.color = fg_color if has_filterset else bg_color
        filterset_label.styles.text_style = "bold" if has_filterset else None
        filterset_label.styles.opacity = 1.0 if has_filterset else 0.5

        # Tmux indicators — show/hide based on availability
        # // [LAW:dataflow-not-control-flow] Always run; state values vary style.
        tmux_available = state.get("tmux_available", False)
        tmux_auto = state.get("tmux_auto_zoom", False)
        tmux_zoomed = state.get("tmux_zoomed", False)

        for widget in self.query(".tmux"):
            widget.set_class(tmux_available, "-available")

        # Launcher chip
        launch_chip = self.query_one("#cmd-launch-tool", Chip)
        active_tool_key = str(state.get("active_launch_tool", "claude") or "claude")
        active_tool_label = active_tool_key.replace("_", " ")
        active_config_name = state.get("active_launch_config_name", "")
        config_suffix = f" [{active_config_name}]" if (active_config_name and active_config_name != "default") else ""
        launch_chip.update(f" c {active_tool_label}{config_suffix} ")

        # Zoom chip
        zoom_chip = self.query_one("#cmd-zoom", Chip)
        zoom_chip.update(" z zoom ")
        zoom_chip.set_class(not tmux_zoomed, "-dim")
        zoom_chip.styles.text_style = "bold reverse" if tmux_zoomed else None

        # Auto-zoom chip
        auto_chip = self.query_one("#cmd-auto-zoom", Chip)
        auto_chip.update(" Z auto ")
        auto_chip.set_class(not tmux_auto, "-dim")
        auto_chip.styles.text_style = "bold reverse" if tmux_auto else None

