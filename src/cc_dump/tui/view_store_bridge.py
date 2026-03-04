"""View store → widget bridge. Builds push callbacks for setup_reactions(). RELOADABLE.

// [LAW:one-way-deps] Depends on view_store (data) and widget modules (push targets).
// [LAW:locality-or-seam] Coupling between store and widgets isolated here.
// [LAW:single-enforcer] Each push callback is the single path from store → widget.
"""

import cc_dump.tui.widget_factory
import cc_dump.tui.custom_footer
import cc_dump.tui.side_channel_panel
import cc_dump.tui.search
from textual.css.query import NoMatches
from cc_dump.tui import action_handlers as _actions


def build_reaction_context(app) -> dict:
    """Build push callbacks for view store reactions.

    Returns dict to merge into store_context before setup_reactions().
    """

    def push_footer(state):
        FollowState = cc_dump.tui.widget_factory.FollowState
        enriched = dict(state)
        enriched["follow_state"] = FollowState(state["follow_state"])
        app.query_one(cc_dump.tui.custom_footer.StatusFooter).update_display(enriched)

    def push_errors(items):
        conv = app._get_conv()
        if conv is not None:
            ErrorItem = cc_dump.tui.error_indicator.ErrorItem
            conv.update_error_items(
                [
                    ErrorItem(
                        str(item.id),
                        str(item.icon),
                        str(item.summary),
                    )
                    for item in items
                ]
            )

    def push_sc_panel(state):
        SideChannelPanelState = cc_dump.tui.side_channel_panel.SideChannelPanelState
        try:
            panel = app.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel).first()
        except NoMatches:
            return
        panel.update_display(SideChannelPanelState(**state))

    def push_panel_change(value):
        app._sync_panel_display(value)
        _actions.refresh_active_panel(app, value)

    def push_sidebar_state(value):
        app._sync_sidebar_panels(value)

    def push_chrome_panels(value):
        logs_visible, info_visible = value
        logs = app._get_logs()
        if logs is not None:
            logs.display = bool(logs_visible)
        info = app._get_info()
        if info is not None:
            info.display = bool(info_visible)

    def push_search_ui(value):
        SearchBarState = cc_dump.tui.search.SearchBarState
        SearchMode = cc_dump.tui.search.SearchMode
        SearchPhase = cc_dump.tui.search.SearchPhase
        phase_raw = str(value.get("phase", SearchPhase.INACTIVE.value))
        try:
            phase = SearchPhase(phase_raw)
        except ValueError:
            phase = SearchPhase.INACTIVE
        modes_raw = int(value.get("modes", int(SearchMode.CASE_INSENSITIVE)))
        try:
            modes = SearchMode(modes_raw)
        except ValueError:
            modes = SearchMode.CASE_INSENSITIVE
        # [LAW:dataflow-not-control-flow] Search bar + footer are updated every projection tick.
        search_state = SearchBarState(
            phase=phase,
            query=str(value.get("query", "")),
            modes=modes,
            cursor_pos=int(value.get("cursor_pos", 0)),
            current_index=int(value.get("current_index", 0)),
            match_count=int(value.get("match_count", 0)),
        )
        bar = app._get_search_bar()
        if bar is not None:
            bar.update_display(search_state)
        footer = app._get_footer()
        if footer is not None:
            footer.display = bool(value.get("footer_visible", True))

    return {
        "push_footer": push_footer,
        "push_errors": push_errors,
        "push_sc_panel": push_sc_panel,
        "push_panel_change": push_panel_change,
        "push_sidebar_state": push_sidebar_state,
        "push_chrome_panels": push_chrome_panels,
        "push_search_ui": push_search_ui,
    }


def enrich_footer_state(state: dict) -> dict:
    """Convert raw footer_state dict to widget-ready form (FollowState enum).

    For direct reads that bypass the reaction (initial hydration, hot-reload).
    """
    FollowState = cc_dump.tui.widget_factory.FollowState
    enriched = dict(state)
    enriched["follow_state"] = FollowState(state["follow_state"])
    return enriched
