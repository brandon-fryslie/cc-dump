"""Panel registry — single source of truth for cycling panel configuration.

// [LAW:one-source-of-truth] All cycling panel metadata lives here.
// [LAW:locality-or-seam] Adding a panel = one entry here + the panel module.

This module is STABLE (not hot-reloadable). It's pure data with no dependencies
on other project modules.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PanelSpec:
    """Specification for a cycling panel."""

    name: str       # "stats", "session"
    css_id: str     # "stats-panel", "session-panel"
    factory: str    # dotted path to factory function


# [LAW:one-source-of-truth] Ordered list of cycling panels
PANEL_REGISTRY: list[PanelSpec] = [
    PanelSpec("stats", "stats-panel", "cc_dump.tui.widget_factory.create_stats_panel"),
    PanelSpec("economics", "economics-panel", "cc_dump.tui.widget_factory.create_economics_panel"),
    PanelSpec("timeline", "timeline-panel", "cc_dump.tui.widget_factory.create_timeline_panel"),
    PanelSpec("session", "session-panel", "cc_dump.tui.session_panel.create_session_panel"),
]

# Derived — kept in sync automatically
PANEL_ORDER = [s.name for s in PANEL_REGISTRY]
PANEL_CSS_IDS = {s.name: s.css_id for s in PANEL_REGISTRY}
