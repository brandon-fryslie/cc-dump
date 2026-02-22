"""Multi-session conversation tab routing tests."""

import pytest

from tests.harness import run_app, strips_to_text


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


async def test_replay_routes_turns_to_per_session_domain_stores():
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
        _ = pilot
        ds_a = app._get_domain_store(session_a)
        ds_b = app._get_domain_store(session_b)

        assert ds_a.completed_count == 2
        assert ds_b.completed_count == 2

        conv_a = app._get_conv(session_key=session_a)
        conv_b = app._get_conv(session_key=session_b)
        assert conv_a is not None
        assert conv_b is not None

        text_a = "".join(strips_to_text(td.strips) for td in conv_a._turns)
        text_b = "".join(strips_to_text(td.strips) for td in conv_b._turns)
        assert "session-a-request" in text_a
        assert "session-a-response" in text_a
        assert "session-b-request" not in text_a
        assert "session-b-response" not in text_a
        assert "session-b-request" in text_b
        assert "session-b-response" in text_b
        assert "session-a-request" not in text_b
        assert "session-a-response" not in text_b


async def test_tab_activation_updates_active_domain_store_alias():
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

        active_store = app._get_active_domain_store()
        assert active_store is app._get_domain_store(session_b)
        assert app._domain_store is active_store
