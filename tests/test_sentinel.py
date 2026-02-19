"""Tests for sentinel interceptor and request pipeline."""

import json
from unittest.mock import MagicMock

import pytest

from cc_dump.proxy import RequestPipeline, _build_synthetic_sse_bytes
from cc_dump.sentinel import extract_sentinel_command, make_interceptor


# ─── extract_sentinel_command ────────────────────────────────────────────────


class TestExtractSentinelCommand:
    """Pure function tests for extract_sentinel_command."""

    def test_string_content_bare_sentinel(self):
        body = {"messages": [{"role": "user", "content": "$$"}]}
        assert extract_sentinel_command(body) == ""

    def test_string_content_with_command(self):
        body = {"messages": [{"role": "user", "content": "$$focus"}]}
        assert extract_sentinel_command(body) == "focus"

    def test_string_content_with_whitespace(self):
        body = {"messages": [{"role": "user", "content": "  $$test  "}]}
        assert extract_sentinel_command(body) == "test"

    def test_block_content_text_type(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "$$hello"}],
                }
            ]
        }
        assert extract_sentinel_command(body) == "hello"

    def test_block_content_first_text_block(self):
        """Only the first text block is checked."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": "..."},
                        {"type": "text", "text": "$$cmd"},
                    ],
                }
            ]
        }
        assert extract_sentinel_command(body) == "cmd"

    def test_block_content_first_text_no_sentinel(self):
        """First text block doesn't have sentinel — return None even if later ones do."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "normal text"},
                        {"type": "text", "text": "$$hidden"},
                    ],
                }
            ]
        }
        assert extract_sentinel_command(body) is None

    def test_no_sentinel(self):
        body = {"messages": [{"role": "user", "content": "hello world"}]}
        assert extract_sentinel_command(body) is None

    def test_mid_text_sentinel(self):
        """Sentinel only triggers at start of content."""
        body = {"messages": [{"role": "user", "content": "hello $$ world"}]}
        assert extract_sentinel_command(body) is None

    def test_empty_messages(self):
        body = {"messages": []}
        assert extract_sentinel_command(body) is None

    def test_no_messages_key(self):
        body = {}
        assert extract_sentinel_command(body) is None

    def test_last_message_not_user(self):
        body = {"messages": [{"role": "assistant", "content": "$$nope"}]}
        assert extract_sentinel_command(body) is None

    def test_multiple_messages_last_is_user(self):
        body = {
            "messages": [
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "$$go"},
            ]
        }
        assert extract_sentinel_command(body) == "go"

    def test_multiple_messages_last_is_assistant(self):
        body = {
            "messages": [
                {"role": "user", "content": "$$go"},
                {"role": "assistant", "content": "response"},
            ]
        }
        assert extract_sentinel_command(body) is None


# ─── _build_synthetic_sse_bytes ──────────────────────────────────────────────


class TestBuildSyntheticSSE:
    """Validate SSE wire format."""

    def test_parseable_sse(self):
        """Output should be parseable SSE with correct event sequence."""
        sse_bytes = _build_synthetic_sse_bytes("[cc-dump]", model="test-model")
        lines = sse_bytes.decode().strip().split("\n\n")

        # Parse each data line
        events = []
        for line in lines:
            assert line.startswith("data: ")
            payload = line[6:]
            if payload == "[DONE]":
                events.append("[DONE]")
            else:
                events.append(json.loads(payload))

        # Verify event type sequence
        types = [e if isinstance(e, str) else e["type"] for e in events]
        assert types == [
            "message_start",
            "content_block_start",
            "content_block_delta",
            "content_block_stop",
            "message_delta",
            "message_stop",
            "[DONE]",
        ]

    def test_response_text_in_delta(self):
        sse_bytes = _build_synthetic_sse_bytes("hello world")
        # Find the content_block_delta
        for line in sse_bytes.decode().strip().split("\n\n"):
            payload = line[6:]
            if payload == "[DONE]":
                continue
            event = json.loads(payload)
            if event["type"] == "content_block_delta":
                assert event["delta"]["text"] == "hello world"
                return
        pytest.fail("No content_block_delta found")

    def test_model_in_message_start(self):
        sse_bytes = _build_synthetic_sse_bytes("x", model="claude-custom")
        for line in sse_bytes.decode().strip().split("\n\n"):
            payload = line[6:]
            if payload == "[DONE]":
                continue
            event = json.loads(payload)
            if event["type"] == "message_start":
                assert event["message"]["model"] == "claude-custom"
                return
        pytest.fail("No message_start found")

    def test_stop_reason_end_turn(self):
        sse_bytes = _build_synthetic_sse_bytes("x")
        for line in sse_bytes.decode().strip().split("\n\n"):
            payload = line[6:]
            if payload == "[DONE]":
                continue
            event = json.loads(payload)
            if event["type"] == "message_delta":
                assert event["delta"]["stop_reason"] == "end_turn"
                return
        pytest.fail("No message_delta found")


# ─── RequestPipeline ─────────────────────────────────────────────────────────


class TestRequestPipeline:
    """Pipeline composition tests."""

    def test_no_transforms_no_interceptors(self):
        pipeline = RequestPipeline()
        body, url, response = pipeline.process({"key": "val"}, "http://example.com")
        assert body == {"key": "val"}
        assert url == "http://example.com"
        assert response is None

    def test_transform_modifies_url(self):
        def swap_url(body, url):
            return body, "http://other.com/v1/messages"

        pipeline = RequestPipeline(transforms=[swap_url])
        body, url, response = pipeline.process({}, "http://original.com")
        assert url == "http://other.com/v1/messages"
        assert response is None

    def test_transform_modifies_body(self):
        def add_field(body, url):
            body["extra"] = True
            return body, url

        pipeline = RequestPipeline(transforms=[add_field])
        body, url, response = pipeline.process({}, "http://x.com")
        assert body["extra"] is True

    def test_transforms_chain(self):
        """Each transform sees the output of the previous."""

        def add_a(body, url):
            body["a"] = True
            return body, url

        def read_a(body, url):
            body["saw_a"] = body.get("a", False)
            return body, url

        pipeline = RequestPipeline(transforms=[add_a, read_a])
        body, _, _ = pipeline.process({}, "http://x.com")
        assert body["saw_a"] is True

    def test_interceptor_returns_response(self):
        def always_intercept(body):
            return "intercepted!"

        pipeline = RequestPipeline(interceptors=[always_intercept])
        body, url, response = pipeline.process({}, "http://x.com")
        assert response == "intercepted!"

    def test_interceptor_none_passes_through(self):
        def nope(body):
            return None

        pipeline = RequestPipeline(interceptors=[nope])
        _, _, response = pipeline.process({}, "http://x.com")
        assert response is None

    def test_first_interceptor_wins(self):
        def first(body):
            return "first"

        def second(body):
            return "second"

        pipeline = RequestPipeline(interceptors=[first, second])
        _, _, response = pipeline.process({}, "http://x.com")
        assert response == "first"

    def test_transform_then_intercept(self):
        """Interceptor sees transformed body."""

        def add_flag(body, url):
            body["flagged"] = True
            return body, url

        def check_flag(body):
            if body.get("flagged"):
                return "was flagged"
            return None

        pipeline = RequestPipeline(transforms=[add_flag], interceptors=[check_flag])
        body, _, response = pipeline.process({}, "http://x.com")
        assert response == "was flagged"
        assert body["flagged"] is True


# ─── make_interceptor ────────────────────────────────────────────────────────


class TestMakeInterceptor:
    """Integration tests for the sentinel interceptor factory."""

    def test_sentinel_triggers_focus_self(self):
        mock_ctrl = MagicMock()
        interceptor = make_interceptor(mock_ctrl)

        body = {"messages": [{"role": "user", "content": "$$"}]}
        result = interceptor(body)

        assert result == "[cc-dump]"
        mock_ctrl.focus_self.assert_called_once()

    def test_non_sentinel_skips(self):
        mock_ctrl = MagicMock()
        interceptor = make_interceptor(mock_ctrl)

        body = {"messages": [{"role": "user", "content": "normal message"}]}
        result = interceptor(body)

        assert result is None
        mock_ctrl.focus_self.assert_not_called()

    def test_no_tmux_controller(self):
        """Works without tmux controller (no-op focus)."""
        interceptor = make_interceptor(None)

        body = {"messages": [{"role": "user", "content": "$$"}]}
        result = interceptor(body)

        assert result == "[cc-dump]"
