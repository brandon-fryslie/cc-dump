"""Multi-session conversation tab routing tests."""

import pytest

from cc_dump.event_types import RequestBodyEvent, ResponseProgressEvent
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


def _make_side_channel_replay_entry(
    *, session_id: str, purpose: str, source_session_id: str, content: str, response_text: str
):
    marker = (
        "<<CC_DUMP_SIDE_CHANNEL:"
        f'{{"run_id":"run-{session_id[:4]}","purpose":"{purpose}","source_session_id":"{source_session_id}"}}'
        ">>\n"
    )
    return _make_replay_entry(
        session_id=session_id,
        content=marker + content,
        response_text=response_text,
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


async def test_side_channel_replay_routes_to_separate_lane_without_primary_contamination():
    session_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    replay_data = [
        _make_replay_entry(
            session_id=session_a,
            content="primary-request",
            response_text="primary-response",
        ),
        _make_side_channel_replay_entry(
            session_id=session_a,
            purpose="block_summary",
            source_session_id=session_a,
            content="side-request",
            response_text="side-response",
        ),
    ]

    async with run_app(replay_data=replay_data) as (pilot, app):
        _ = pilot
        side_key = f"side-channel:block_summary:{session_a}"
        primary_ds = app._get_domain_store(session_a)
        side_ds = app._get_domain_store(side_key)

        assert primary_ds.completed_count == 2
        assert side_ds.completed_count == 2

        primary_conv = app._get_conv(session_key=session_a)
        side_conv = app._get_conv(session_key=side_key)
        assert primary_conv is not None
        assert side_conv is not None

        primary_text = "".join(strips_to_text(td.strips) for td in primary_conv._turns)
        side_text = "".join(strips_to_text(td.strips) for td in side_conv._turns)

        assert "primary-request" in primary_text
        assert "primary-response" in primary_text
        assert "side-request" not in primary_text
        assert "side-response" not in primary_text

        assert "side-request" in side_text
        assert "side-response" in side_text
        assert "primary-request" not in side_text
        assert "primary-response" not in side_text


async def test_side_channel_stream_progress_routes_to_side_lane_without_primary_leakage():
    session_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user_id = f"user_deadbeef_account_{_ACCOUNT_ID}_session_{session_a}"
    side_request_id = "req-side-progress"
    main_request_id = "req-main-progress"
    side_marker = (
        "<<CC_DUMP_SIDE_CHANNEL:"
        f'{{"run_id":"run-{session_a[:4]}","purpose":"block_summary","source_session_id":"{session_a}"}}'
        ">>\n"
    )

    async with run_app() as (pilot, app):
        app._event_queue.put(
            RequestBodyEvent(
                body={
                    "model": "claude-haiku-4-5",
                    "metadata": {"user_id": user_id},
                    "messages": [{"role": "user", "content": "primary-stream-request"}],
                },
                request_id=main_request_id,
                seq=1,
            )
        )
        app._event_queue.put(
            ResponseProgressEvent(
                request_id=main_request_id,
                seq=2,
                delta_text="primary stream chunk",
            )
        )

        app._event_queue.put(
            RequestBodyEvent(
                body={
                    "model": "claude-haiku-4-5",
                    "metadata": {"user_id": user_id},
                    "messages": [
                        {
                            "role": "user",
                            "content": side_marker + "side-stream-request",
                        }
                    ],
                },
                request_id=side_request_id,
                seq=3,
            )
        )
        app._event_queue.put(
            ResponseProgressEvent(
                request_id=side_request_id,
                seq=4,
                delta_text="side stream chunk",
            )
        )
        await pilot.pause()

        side_key = f"side-channel:block_summary:{session_a}"
        primary_ds = app._get_domain_store(session_a)
        side_ds = app._get_domain_store(side_key)

        primary_blocks = primary_ds.get_stream_blocks(main_request_id)
        side_blocks = side_ds.get_stream_blocks(side_request_id)
        assert primary_blocks
        assert side_blocks

        primary_text = "".join(
            getattr(block, "content", "")
            for block in primary_blocks
            if isinstance(getattr(block, "content", None), str)
        )
        side_text = "".join(
            getattr(block, "content", "")
            for block in side_blocks
            if isinstance(getattr(block, "content", None), str)
        )

        assert "primary stream chunk" in primary_text
        assert "side stream chunk" not in primary_text
        assert "side stream chunk" in side_text
        assert "primary stream chunk" not in side_text
