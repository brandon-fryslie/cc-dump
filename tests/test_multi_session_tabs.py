"""Multi-session conversation tab routing tests."""

import pytest

import cc_dump.providers
from cc_dump.pipeline.har_replayer import ReplayPair

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
    return ReplayPair(
        request_headers={"content-type": "application/json"},
        request_body=req_body,
        response_status=200,
        response_headers={"content-type": "application/json"},
        complete_message=complete_message,
        provider="anthropic",
    )



async def test_all_sessions_route_to_default_tab():
    """All Anthropic sessions share the default tab's single DomainStore."""
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
        default_ds = app._sessions.default().domain_store

        # Both sessions' turns land in the single default DomainStore.
        # Combined turns: each request-response pair is 1 turn = 1 per session.
        assert default_ds.completed_count >= 2

        # Only one Claude tab exists (the default), not per-session tabs.
        anthropic_sessions = [
            s for s in app._sessions.all()
            if s.provider == cc_dump.providers.DEFAULT_PROVIDER_KEY
        ]
        assert len(anthropic_sessions) == 1
        assert anthropic_sessions[0].is_default

        # Both sessions' content visible in the single ConversationView.
        conv = app._get_conv(session_key=app._sessions.default().key)
        assert conv is not None
        text = "".join(strips_to_text(td.strips) for td in conv._turns)
        assert "session-a-request" in text
        assert "session-a-response" in text
        assert "session-b-request" in text
        assert "session-b-response" in text


async def test_single_claude_tab_active_domain_store():
    """Active domain store is always the default when on the Claude tab."""
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
        active_store = app._sessions.active().domain_store
        default_store = app._sessions.default().domain_store
        assert active_store is default_store


async def test_session_id_tracks_most_recent_session():
    """Provider.last_notified_session tracks the most recent session from API metadata."""
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
        # session_b was processed last, so default provider's last_notified should reflect it.
        assert app._providers.default().last_notified_session == session_b
        # _active_resume_session_id falls through to default provider on the default tab.
        assert app._active_resume_session_id() == session_b


async def test_session_boundary_tracking():
    """DomainStore tracks session boundaries for navigation."""
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
        default_ds = app._sessions.default().domain_store
        boundaries = default_ds.get_session_boundaries()
        # Should have at least one boundary (when session changes from a to b).
        # Session a is the first session seen, so a NewSessionBlock fires for it too.
        session_ids = [sid for sid, _idx in boundaries]
        assert session_a in session_ids
        assert session_b in session_ids


