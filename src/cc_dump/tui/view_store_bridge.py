"""View store → widget bridge. Builds push callbacks for setup_reactions(). RELOADABLE.

// [LAW:one-way-deps] Depends on view_store (data) and widget modules (push targets).
// [LAW:locality-or-seam] Coupling between store and widgets isolated here.
// [LAW:single-enforcer] Each push callback is the single path from store → widget.
"""

import cc_dump.tui.widget_factory
import cc_dump.tui.custom_footer
import cc_dump.tui.side_channel_panel
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
            conv.update_error_items(items)

    def push_sc_panel(state):
        SideChannelPanelState = cc_dump.tui.side_channel_panel.SideChannelPanelState
        app.screen.query(
            cc_dump.tui.side_channel_panel.SideChannelPanel
        ).first().update_display(SideChannelPanelState(**state))

    def push_panel_change(value):
        app._sync_panel_display(value)
        _actions.refresh_active_panel(app, value)

    return {
        "push_footer": push_footer,
        "push_errors": push_errors,
        "push_sc_panel": push_sc_panel,
        "push_panel_change": push_panel_change,
    }


def enrich_footer_state(state: dict) -> dict:
    """Convert raw footer_state dict to widget-ready form (FollowState enum).

    For direct reads that bypass the reaction (initial hydration, hot-reload).
    """
    FollowState = cc_dump.tui.widget_factory.FollowState
    enriched = dict(state)
    enriched["follow_state"] = FollowState(state["follow_state"])
    return enriched
