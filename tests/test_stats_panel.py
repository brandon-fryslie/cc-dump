"""StatsPanel aggregate lane count tests."""

from cc_dump.tui.widget_factory import StatsPanel


class _AnalyticsStoreStub:
    def get_dashboard_snapshot(self, current_turn=None):
        _ = current_turn
        return {
            "summary": {
                "turn_count": 1,
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "input_total": 10,
                "total_tokens": 15,
                "cache_pct": 0.0,
                "cost_usd": 0.001,
                "cache_savings_usd": 0.0,
                "active_model_count": 1,
                "latest_model_label": "Sonnet",
            },
            "timeline": [],
            "models": [],
        }


class _DomainStoreStub:
    def __init__(self, completed: dict[str, int], active: dict[str, int]):
        self._completed = completed
        self._active = active

    def get_completed_lane_counts(self) -> dict[str, int]:
        return dict(self._completed)

    def get_active_lane_counts(self) -> dict[str, int]:
        return dict(self._active)


def test_refresh_from_store_sets_active_and_aggregate_lane_counts():
    panel = StatsPanel()
    store = _AnalyticsStoreStub()
    active_store = _DomainStoreStub(
        completed={"main": 2, "subagent": 1, "unknown": 0},
        active={"main": 1, "subagent": 0, "unknown": 0},
    )
    extra_store = _DomainStoreStub(
        completed={"main": 3, "subagent": 2, "unknown": 1},
        active={"main": 0, "subagent": 1, "unknown": 0},
    )

    panel.refresh_from_store(
        store,
        domain_store=active_store,
        all_domain_stores=(active_store, extra_store),
    )

    summary = panel._last_snapshot["summary"]
    assert summary["main_turns"] == 2
    assert summary["subagent_turns"] == 1
    assert summary["active_main_streams"] == 1
    assert summary["all_main_turns"] == 5
    assert summary["all_subagent_turns"] == 3
    assert summary["all_unknown_turns"] == 1
    assert summary["all_active_subagent_streams"] == 1
