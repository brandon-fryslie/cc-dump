"""Widget factory and state management for TUI panels.

This module provides factory functions for creating Textual widgets and managing
their state across hot-reloads. It imports stable boundary modules using qualified
imports and reloadable modules via the hot_reload registry.
"""

from textual.widgets import Static

import cc_dump.db_queries
import cc_dump.tui.panel_renderers


# ─── Stats Panel ──────────────────────────────────────────────────────────────


class StatsPanel(Static):
    """Panel showing session-level token statistics.

    Queries database as single source of truth.
    """

    def __init__(self):
        super().__init__("")
        self.request_count = 0
        self.models_seen: set = set()

    def increment_request_count(self):
        """Increment request counter."""
        self.request_count += 1

    def add_model(self, model: str):
        """Track a seen model."""
        if model:
            self.models_seen.add(model)

    def refresh_from_db(self, db_path: str, session_id: str, current_turn: dict = None):
        """Refresh panel data from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
            current_turn: Optional in-progress turn data to merge
        """
        if not db_path or not session_id:
            self._refresh_display(0, 0, 0, 0)
            return

        # Query stats from database
        stats = cc_dump.db_queries.get_session_stats(db_path, session_id, current_turn)

        # Update display
        self._refresh_display(
            stats["input_tokens"],
            stats["output_tokens"],
            stats["cache_read_tokens"],
            stats["cache_creation_tokens"],
        )

    def _refresh_display(self, input_tokens: int, output_tokens: int,
                        cache_read_tokens: int, cache_creation_tokens: int):
        """Rebuild the stats display."""
        text = cc_dump.tui.panel_renderers.render_stats_panel(
            self.request_count,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
            self.models_seen,
        )
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {
            "request_count": self.request_count,
            "models_seen": set(self.models_seen),
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self.request_count = state.get("request_count", 0)
        self.models_seen = state.get("models_seen", set())
        # Trigger display refresh (will need DB query to get token counts)
        self._refresh_display(0, 0, 0, 0)


class ToolEconomicsPanel(Static):
    """Panel showing per-tool token usage aggregates.

    Queries database as single source of truth.
    """

    def __init__(self):
        super().__init__("")

    def refresh_from_db(self, db_path: str, session_id: str):
        """Refresh panel data from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
        """
        if not db_path or not session_id:
            self._refresh_display([])
            return

        # Query tool economics with real tokens and cache attribution
        rows = cc_dump.db_queries.get_tool_economics(db_path, session_id)
        self._refresh_display(rows)

    def _refresh_display(self, rows):
        """Rebuild the economics table."""
        text = cc_dump.tui.panel_renderers.render_economics_panel(rows)
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # No state to preserve - queries DB on demand

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._refresh_display([])


class TimelinePanel(Static):
    """Panel showing per-turn context growth over time.

    Queries database as single source of truth.
    """

    def __init__(self):
        super().__init__("")

    def refresh_from_db(self, db_path: str, session_id: str):
        """Refresh panel data from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
        """
        if not db_path or not session_id:
            self._refresh_display([])
            return

        # Query timeline data
        timeline = cc_dump.db_queries.get_turn_timeline(db_path, session_id)

        # Build TurnBudget objects from timeline data
        import json
        import cc_dump.analysis

        budgets = []
        for row in timeline:
            # Parse request JSON to compute estimated budgets
            try:
                request_body = json.loads(row["request_json"])
                budget = cc_dump.analysis.compute_turn_budget(request_body)
                # Fill in actual token counts from DB
                budget.actual_input_tokens = row["input_tokens"]
                budget.actual_output_tokens = row["output_tokens"]
                budget.actual_cache_read_tokens = row["cache_read_tokens"]
                budget.actual_cache_creation_tokens = row["cache_creation_tokens"]
                budgets.append(budget)
            except (json.JSONDecodeError, KeyError):
                # Skip malformed data
                continue

        self._refresh_display(budgets)

    def _refresh_display(self, budgets):
        """Rebuild the timeline table."""
        text = cc_dump.tui.panel_renderers.render_timeline_panel(budgets)
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # No state to preserve - queries DB on demand

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._refresh_display([])
