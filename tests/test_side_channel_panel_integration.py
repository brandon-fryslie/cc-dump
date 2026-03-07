"""Integration-level smoke tests for surviving Side Channel panel entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cc_dump.ai.data_dispatcher import UtilityResult
from cc_dump.tui.chip import Chip
from cc_dump.tui.side_channel_panel import SideChannelPanel, SideChannelPanelState
from tests.harness import run_app


pytestmark = pytest.mark.textual


@dataclass
class _StubDispatcher:
    def run_utility(self, *_args, **_kwargs) -> UtilityResult:
        return UtilityResult(
            utility_id="turn_title",
            text="Proposed Title",
            source="ai",
            elapsed_ms=3,
            error="",
        )


async def test_side_channel_panel_exposes_remaining_entrypoint_controls():
    async with run_app() as (pilot, app):
        app.action_toggle_side_channel()
        await pilot.pause()
        panel = app.screen.query(SideChannelPanel).first()
        panel.update_display(
            SideChannelPanelState(
                enabled=True,
                loading=False,
                active_action="",
                result_text="",
                result_source="",
                result_elapsed_ms=0,
                purpose_usage={},
            )
        )
        expected = {
            "sc-qa_estimate": "app.sc_qa_estimate",
            "sc-qa_submit": "app.sc_qa_submit",
            "sc-handoff_draft": "app.sc_preview_handoff",
            "sc-utility_run": "app.sc_utility_run",
        }
        for widget_id, action in expected.items():
            chip = panel.query_one(f"#{widget_id}", Chip)
            assert chip._action == action


async def test_side_channel_panel_utility_flow_smoke():
    async with run_app() as (pilot, app):
        app._data_dispatcher = _StubDispatcher()
        app._app_state["recent_messages"] = [
            {"role": "user", "content": "propose a short title"},
            {"role": "assistant", "content": "implemented lane routing"},
        ]
        app.action_toggle_side_channel()
        await pilot.pause()

        app.action_sc_utility_run()
        await pilot.pause()

        assert "utility result" in app._view_store.get("sc:result_text")
        assert "utility_id: turn_title" in app._view_store.get("sc:result_text")
        assert "Proposed Title" in app._view_store.get("sc:result_text")
