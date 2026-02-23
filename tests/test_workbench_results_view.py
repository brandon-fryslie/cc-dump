"""Conversation-tab Workbench results view tests."""

from __future__ import annotations

import pytest

from tests.harness import run_app


pytestmark = pytest.mark.textual


_ACCOUNT_ID = "11111111-2222-3333-4444-555555555555"


def _make_replay_entry(*, session_id: str, content: str, response_text: str):
    user_id = f"user_deadbeef_account_{_ACCOUNT_ID}_session_{session_id}"
    req_body = {
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 1024,
        "metadata": {"user_id": user_id},
        "messages": [{"role": "user", "content": content}],
    }
    complete_message = {
        "id": f"msg-{session_id[:8]}",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5-20250929",
        "content": [{"type": "text", "text": response_text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    return (
        {"content-type": "application/json"},
        req_body,
        200,
        {"content-type": "application/json"},
        complete_message,
    )


async def test_workbench_results_tab_receives_full_output_and_metadata():
    async with run_app() as (pilot, app):
        app.action_toggle_side_channel()
        await pilot.pause()

        app._set_side_channel_result(
            text="## Session Summary\n\n- one\n- two\n",
            source="ai",
            elapsed_ms=42,
            loading=False,
            active_action="qa_submit",
            focus_results=True,
        )
        await pilot.pause()

        tabs = app._get_conv_tabs()
        assert tabs is not None
        assert tabs.active == app._workbench_tab_id

        workbench = app._get_workbench_results_view()
        assert workbench is not None
        assert workbench._last_text.startswith("## Session Summary")
        assert workbench._last_source == "ai"
        assert workbench._last_elapsed_ms == 42

        assert "source=ai" in workbench._last_meta
        assert "elapsed=42ms" in workbench._last_meta


async def test_switching_to_workbench_tab_does_not_lose_active_session_context():
    session_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    session_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    replay_data = [
        _make_replay_entry(
            session_id=session_a,
            content="session-a-request",
            response_text="session-a-response",
        ),
        _make_replay_entry(
            session_id=session_b,
            content="session-b-request",
            response_text="session-b-response",
        ),
    ]
    async with run_app(replay_data=replay_data) as (pilot, app):
        tabs = app._get_conv_tabs()
        assert tabs is not None
        tab_b = app._session_tab_ids[session_b]
        tabs.active = tab_b
        await pilot.pause()
        assert app._active_session_key == session_b

        app._show_workbench_results_tab()
        await pilot.pause()
        assert tabs.active == app._workbench_tab_id
        assert app._active_session_key == session_b

        tabs.active = tab_b
        await pilot.pause()
        assert app._active_session_key == session_b
