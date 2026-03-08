"""Custom Footer widget with composed Textual widgets."""

from snarfx import textual as stx
from textual.color import Color
from textual.containers import Horizontal

import cc_dump.tui.rendering
import cc_dump.tui.widget_factory
import cc_dump.io.logging_setup
from cc_dump.core.formatting import VisState, HIDDEN
from cc_dump.tui.chip import Chip
from cc_dump.tui.store_widget import StoreWidget


class StatusFooter(StoreWidget):
    """Data-driven footer built from composed widgets.

    // [LAW:dataflow-not-control-flow] Render pipeline is fixed; data determines style.
    // [LAW:single-enforcer] _setup_store_reactions() is the sole subscription entry.
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

    /* Dim chips: same hover pattern */
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

    def _setup_store_reactions(self) -> list:
        # [LAW:single-enforcer] Footer self-subscribes to footer_state; fires immediately
        # on mount (post-compose) so children are guaranteed ready.
        store = self.app.view_store
        return [
            stx.reaction(
                self.app,
                lambda: store.footer_state.get(),
                self._apply_footer_state,
                fire_immediately=True,
            ),
            stx.reaction(
                self.app,
                lambda: bool(store.search_ui_state.get().footer_visible),
                self._apply_footer_visibility,
                fire_immediately=True,
            ),
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
            yield Chip(
                " c launch ",
                action="app.launch_tool",
                id="cmd-launch-tool",
                classes="tmux",
            )
        # Line 3: log row
        runtime = cc_dump.io.logging_setup.get_runtime()
        log_path = runtime.file_path if runtime is not None else ""
        copy_action = "app.copy_log_path" if log_path else None
        with Horizontal(id="footer-log-row"):
            yield Chip(
                " log: ",
                action=copy_action,
                hover_label=" copy ",
                id="footer-log-label",
                classes="-copyable",
            )
            yield Chip(
                " L tail ",
                action="app.open_tmux_log_tail",
                id="cmd-tail-log",
                classes="tmux",
            )
            yield Chip(
                f" {log_path} " if log_path else " (unavailable) ",
                action=copy_action,
                id="footer-log",
                classes="-copyable",
            )

    def _apply_footer_state(self, state: dict[str, object]) -> None:
        # [LAW:dataflow-not-control-flow] State values determine rendering, no branching.
        # [LAW:one-source-of-truth] exception: runtime/theme becomes authoritative only after app mount.
        if not self.is_attached:
            return
        runtime = cc_dump.tui.rendering.get_runtime_from_owner(self)
        if runtime.theme_colors is None:
            return
        tc = cc_dump.tui.rendering.get_theme_colors(runtime=runtime)
        # Enrich raw store value (follow_state string → FollowState enum)
        FollowState = cc_dump.tui.widget_factory.FollowState
        enriched = dict(state)
        enriched["follow_state"] = FollowState(state["follow_state"])

        bg_color = Color.parse(tc.background)
        fg_color = Color.parse(tc.foreground)
        self._apply_category_row(enriched, tc)
        self._apply_follow_chip(enriched, bg_color, fg_color)
        self._apply_tmux_controls(enriched)

    def _apply_category_row(self, state: dict[str, object], tc) -> None:
        for key, name in self._CATEGORY_ITEMS:
            chip = self.query_one(f"#cat-{name}", Chip)
            vis = state.get(name, HIDDEN)
            icon = self._VIS_ICONS[vis]
            chip.update(f" {key} {name} {icon} ")

            _, bg_hex, fg_hex = tc.filter_colors[name]
            # // [LAW:dataflow-not-control-flow] Style derived from vis.visible value.
            chip.set_class(not vis.visible, "-hidden")
            chip.styles.background = Color.parse(bg_hex)
            chip.styles.color = Color.parse(fg_hex)

    def _apply_follow_chip(self, state: dict[str, object], bg_color: Color, fg_color: Color) -> None:
        # // [LAW:dataflow-not-control-flow] Style + label derived from follow_state via table.
        FollowState = cc_dump.tui.widget_factory.FollowState
        follow_state = state.get("follow_state", FollowState.ACTIVE)
        follow_chip = self.query_one("#cmd-follow", Chip)
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

    def _apply_tmux_controls(self, state: dict[str, object]) -> None:
        # // [LAW:dataflow-not-control-flow] Always run; state values vary style.
        tmux_available = bool(state.get("tmux_available", False))
        for widget in self.query(".tmux"):
            widget.set_class(tmux_available, "-available")

        launch_chip = self.query_one("#cmd-launch-tool", Chip)
        active_tool_key = str(state.get("active_launch_tool", "claude") or "claude")
        active_tool_label = active_tool_key.replace("_", " ")
        active_config_name = state.get("active_launch_config_name", "")
        config_suffix = (
            f" [{active_config_name}]"
            if (active_config_name and active_config_name != "default")
            else ""
        )
        launch_chip.update(f" c {active_tool_label}{config_suffix} ")

    def _apply_footer_visibility(self, footer_visible: bool) -> None:
        self.display = bool(footer_visible)
