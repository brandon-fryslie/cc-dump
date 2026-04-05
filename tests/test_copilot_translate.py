"""Tests for Anthropic ↔ Copilot translation (Responses API + Chat Completions)."""

import json
import pytest

from cc_dump.pipeline.copilot_translate import (
    anthropic_to_copilot_request,
    copilot_sse_to_anthropic_events,
    CopilotSSEParser,
    TranslationState,
    anthropic_sse_line,
    copilot_upstream_url,
    anthropic_to_chat_completions_request,
    chat_chunk_to_anthropic_events,
    ChatTranslationState,
    copilot_chat_completions_url,
    copilot_chat_headers,
)


# ─── Request Translation ───────────────────────────────────────────────────


class TestAnthropicToCopilotRequest:
    """anthropic_to_copilot_request translates Anthropic Messages → Responses API."""

    def test_basic_text_message(self):
        body = {
            "model": "claude-sonnet-4-20250514",
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1024,
            "stream": True,
        }
        result = anthropic_to_copilot_request(body)
        assert result["model"] == "claude-sonnet-4"
        assert result["instructions"] == "You are helpful."
        assert result["stream"] is True
        assert result["max_output_tokens"] == 1024
        assert result["store"] is False
        assert len(result["input"]) == 1
        assert result["input"][0]["type"] == "message"
        assert result["input"][0]["role"] == "user"
        assert result["input"][0]["content"][0]["type"] == "input_text"
        assert result["input"][0]["content"][0]["text"] == "Hello"

    def test_system_as_content_blocks(self):
        body = {
            "model": "claude-sonnet-4-20250514",
            "system": [
                {"type": "text", "text": "Part 1."},
                {"type": "text", "text": "Part 2."},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 100,
        }
        result = anthropic_to_copilot_request(body)
        assert result["instructions"] == "Part 1.\n\nPart 2."

    def test_tool_use_translation(self):
        body = {
            "model": "claude-sonnet-4-20250514",
            "messages": [
                {"role": "user", "content": "Run ls"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Running command."},
                        {
                            "type": "tool_use",
                            "id": "tool_abc",
                            "name": "bash",
                            "input": {"command": "ls"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_abc",
                            "content": "file.py",
                        },
                    ],
                },
            ],
            "max_tokens": 100,
        }
        result = anthropic_to_copilot_request(body)
        items = result["input"]
        # user text → function_call → function_call_output
        types = [i["type"] for i in items]
        assert types == ["message", "message", "function_call", "function_call_output"]

        fc = items[2]
        assert fc["name"] == "bash"
        assert fc["call_id"] == "tool_abc"
        assert json.loads(fc["arguments"]) == {"command": "ls"}

        fco = items[3]
        assert fco["call_id"] == "tool_abc"
        assert fco["output"] == "file.py"

    def test_tool_definition_translation(self):
        body = {
            "model": "claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ],
            "max_tokens": 100,
        }
        result = anthropic_to_copilot_request(body)
        tool = result["tools"][0]
        assert tool["type"] == "function"
        assert tool["name"] == "read_file"
        assert tool["parameters"]["properties"]["path"]["type"] == "string"

    def test_model_mapping(self):
        for anth, expected in [
            ("claude-sonnet-4-6", "claude-sonnet-4.6"),
            ("claude-opus-4-6", "claude-opus-4.6"),
            ("claude-sonnet-4-20250514", "claude-sonnet-4"),  # dated suffix stripped
            ("claude-haiku-4-5-20251001", "claude-haiku-4.5"),  # dated suffix stripped
            ("unknown-model", "unknown-model"),  # pass-through
        ]:
            body = {"model": anth, "messages": [], "max_tokens": 100}
            assert anthropic_to_copilot_request(body)["model"] == expected


# ─── SSE Response Translation ──────────────────────────────────────────────


class TestCopilotSSEToAnthropic:
    """copilot_sse_to_anthropic_events translates Responses API SSE → Anthropic SSE."""

    def _run_events(self, copilot_events):
        """Run a sequence of Copilot events through the translator."""
        state = TranslationState()
        all_anthropic = []
        for etype, data in copilot_events:
            all_anthropic.extend(copilot_sse_to_anthropic_events(etype, data, state))
        return all_anthropic, state

    def test_text_response(self):
        events = [
            ("response.created", {"response": {"model": "gpt-5.3-codex"}}),
            ("response.output_item.added", {"item": {"type": "message", "id": "i1"}}),
            ("response.output_text.delta", {"delta": "Hello", "item_id": "i1"}),
            ("response.output_item.done", {"item": {"type": "message", "id": "i1"}}),
            ("response.completed", {"response": {"usage": {"input_tokens": 10, "output_tokens": 5}}}),
        ]
        anth, state = self._run_events(events)
        types = [e["type"] for e in anth]
        assert types == [
            "message_start",
            "content_block_start",
            "content_block_delta",
            "content_block_stop",
            "message_delta",
            "message_stop",
        ]
        assert anth[0]["message"]["model"] == "gpt-5.3-codex"
        assert anth[1]["content_block"]["type"] == "text"
        assert anth[2]["delta"]["text"] == "Hello"
        assert anth[4]["usage"]["output_tokens"] == 5

    def test_tool_call_response(self):
        events = [
            ("response.created", {"response": {"model": "m"}}),
            ("response.output_item.added", {"item": {"type": "function_call", "id": "i1", "name": "bash", "call_id": "call_x"}}),
            ("response.function_call_arguments.delta", {"delta": '{"cmd":', "item_id": "i1"}),
            ("response.function_call_arguments.delta", {"delta": '"ls"}', "item_id": "i1"}),
            ("response.output_item.done", {"item": {"type": "function_call", "id": "i1"}}),
            ("response.completed", {"response": {"usage": {"input_tokens": 10, "output_tokens": 5}}}),
        ]
        anth, _ = self._run_events(events)
        types = [e["type"] for e in anth]
        assert types == [
            "message_start",
            "content_block_start",
            "content_block_delta",
            "content_block_delta",
            "content_block_stop",
            "message_delta",
            "message_stop",
        ]
        assert anth[1]["content_block"]["type"] == "tool_use"
        assert anth[1]["content_block"]["name"] == "bash"
        assert anth[1]["content_block"]["id"] == "call_x"
        assert anth[2]["delta"]["type"] == "input_json_delta"

    def test_reasoning_items_are_skipped(self):
        events = [
            ("response.created", {"response": {"model": "m"}}),
            ("response.output_item.added", {"item": {"type": "reasoning", "id": "r1"}}),
            ("response.output_item.done", {"item": {"type": "reasoning", "id": "r1"}}),
            ("response.completed", {"response": {"usage": {"input_tokens": 0, "output_tokens": 0}}}),
        ]
        anth, _ = self._run_events(events)
        types = [e["type"] for e in anth]
        # reasoning produces no content blocks — only message envelope
        assert "content_block_start" not in types
        assert types == ["message_start", "message_delta", "message_stop"]


# ─── SSE Parser ────────────────────────────────────────────────────────────


class TestCopilotSSEParser:
    """CopilotSSEParser handles two-line event:/data: SSE format."""

    def test_parse_complete_event(self):
        parser = CopilotSSEParser()
        raw = b'event: response.created\ndata: {"response":{"model":"m"}}\n\n'
        results = parser.feed(raw)
        assert len(results) == 1
        assert results[0][0] == "response.created"
        assert results[0][1]["response"]["model"] == "m"

    def test_parse_across_chunks(self):
        parser = CopilotSSEParser()
        assert parser.feed(b"event: response.cre") == []
        assert parser.feed(b"ated\n") == []
        results = parser.feed(b'data: {"x":1}\n\n')
        assert len(results) == 1
        assert results[0][0] == "response.created"


# ─── URL helpers ───────────────────────────────────────────────────────────


class TestCopilotUpstreamUrl:
    def test_builds_responses_url(self):
        assert copilot_upstream_url("https://api.individual.githubcopilot.com") == \
            "https://api.individual.githubcopilot.com/responses"

    def test_strips_trailing_slash(self):
        assert copilot_upstream_url("https://example.com/") == \
            "https://example.com/responses"


# ─── Chat Completions Request Translation ─────────────────────────────────


class TestAnthropicToChatCompletionsRequest:
    """anthropic_to_chat_completions_request translates Anthropic → Chat Completions."""

    def test_basic_text_message(self):
        body = {
            "model": "claude-sonnet-4-6",
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1024,
            "stream": True,
        }
        result = anthropic_to_chat_completions_request(body)
        assert result["model"] == "claude-sonnet-4.6"
        assert result["stream"] is True
        assert result["max_tokens"] == 1024
        assert result["store"] is False
        # System prompt becomes first message
        assert result["messages"][0] == {"role": "system", "content": "You are helpful."}
        assert result["messages"][1] == {"role": "user", "content": "Hello"}

    def test_tool_use_and_tool_result(self):
        body = {
            "model": "claude-sonnet-4-6",
            "messages": [
                {"role": "user", "content": "Run ls"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Running command."},
                        {
                            "type": "tool_use",
                            "id": "tool_abc",
                            "name": "bash",
                            "input": {"command": "ls"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_abc",
                            "content": "file.py",
                        },
                    ],
                },
            ],
            "max_tokens": 100,
        }
        result = anthropic_to_chat_completions_request(body)
        msgs = result["messages"]
        assert msgs[0] == {"role": "user", "content": "Run ls"}
        # Assistant message with tool_calls
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "Running command."
        assert len(msgs[1]["tool_calls"]) == 1
        tc = msgs[1]["tool_calls"][0]
        assert tc["id"] == "tool_abc"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "bash"
        assert json.loads(tc["function"]["arguments"]) == {"command": "ls"}
        # Tool result → tool role
        assert msgs[2]["role"] == "tool"
        assert msgs[2]["tool_call_id"] == "tool_abc"
        assert msgs[2]["content"] == "file.py"

    def test_tool_definitions(self):
        body = {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ],
            "max_tokens": 100,
        }
        result = anthropic_to_chat_completions_request(body)
        tool = result["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "read_file"
        assert tool["function"]["parameters"]["properties"]["path"]["type"] == "string"

    def test_tool_choice_mapping(self):
        for anth_tc, expected in [
            ({"type": "auto"}, "auto"),
            ({"type": "any"}, "required"),
            ({"type": "none"}, "none"),
            ({"type": "tool", "name": "bash"}, {"type": "function", "function": {"name": "bash"}}),
        ]:
            body = {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
                "tool_choice": anth_tc,
                "max_tokens": 100,
            }
            result = anthropic_to_chat_completions_request(body)
            assert result["tool_choice"] == expected

    def test_model_mapping_with_dated_suffix(self):
        for anth, expected in [
            ("claude-sonnet-4-6", "claude-sonnet-4.6"),
            ("claude-haiku-4-5-20251001", "claude-haiku-4.5"),
            ("claude-sonnet-4-20250514", "claude-sonnet-4"),
            ("unknown-model", "unknown-model"),
        ]:
            body = {"model": anth, "messages": [], "max_tokens": 100}
            assert anthropic_to_chat_completions_request(body)["model"] == expected


# ─── Chat Completions SSE Response Translation ────────────────────────────


class TestChatChunkToAnthropicEvents:
    """chat_chunk_to_anthropic_events translates Chat Completions SSE chunks."""

    def test_text_streaming(self):
        state = ChatTranslationState()
        events: list[dict] = []

        # First chunk with model info
        events.extend(chat_chunk_to_anthropic_events({
            "model": "claude-sonnet-4.6",
            "choices": [{"delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0},
        }, state))

        # Text deltas
        events.extend(chat_chunk_to_anthropic_events({
            "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}],
        }, state))
        events.extend(chat_chunk_to_anthropic_events({
            "choices": [{"delta": {"content": " world"}, "finish_reason": None}],
        }, state))

        # Finish
        events.extend(chat_chunk_to_anthropic_events({
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }, state))

        types = [e["type"] for e in events]
        assert types == [
            "message_start",
            "content_block_start",  # opened by "" content in first chunk
            "content_block_delta",  # ""
            "content_block_delta",  # "Hello" — reuses same block
            "content_block_delta",  # " world"
            "content_block_stop",
            "message_delta",
            "message_stop",
        ]
        assert events[0]["message"]["model"] == "claude-sonnet-4.6"
        assert events[3]["delta"]["text"] == "Hello"
        assert events[4]["delta"]["text"] == " world"
        assert events[6]["delta"]["stop_reason"] == "end_turn"

    def test_tool_call_streaming(self):
        state = ChatTranslationState()
        events: list[dict] = []

        # First chunk
        events.extend(chat_chunk_to_anthropic_events({
            "model": "claude-sonnet-4.6",
            "choices": [{"delta": {"role": "assistant"}, "finish_reason": None}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0},
        }, state))

        # Tool call start
        events.extend(chat_chunk_to_anthropic_events({
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "id": "call_123",
                "type": "function",
                "function": {"name": "bash", "arguments": ""},
            }]}, "finish_reason": None}],
        }, state))

        # Tool call argument deltas
        events.extend(chat_chunk_to_anthropic_events({
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "function": {"arguments": '{"cmd":'},
            }]}, "finish_reason": None}],
        }, state))
        events.extend(chat_chunk_to_anthropic_events({
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "function": {"arguments": '"ls"}'},
            }]}, "finish_reason": None}],
        }, state))

        # Finish
        events.extend(chat_chunk_to_anthropic_events({
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8},
        }, state))

        types = [e["type"] for e in events]
        assert "content_block_start" in types
        assert "content_block_delta" in types

        # Find tool_use content_block_start
        tool_starts = [e for e in events if e.get("type") == "content_block_start"
                       and e.get("content_block", {}).get("type") == "tool_use"]
        assert len(tool_starts) == 1
        assert tool_starts[0]["content_block"]["name"] == "bash"
        assert tool_starts[0]["content_block"]["id"] == "call_123"

        # Check args deltas are input_json_delta
        arg_deltas = [e for e in events if e.get("type") == "content_block_delta"
                      and e.get("delta", {}).get("type") == "input_json_delta"]
        assert len(arg_deltas) >= 2

        # Check stop reason
        msg_delta = [e for e in events if e.get("type") == "message_delta"]
        assert msg_delta[0]["delta"]["stop_reason"] == "tool_use"

    def test_stop_reason_mapping(self):
        for cc_reason, anth_reason in [
            ("stop", "end_turn"),
            ("tool_calls", "tool_use"),
            ("length", "max_tokens"),
            ("content_filter", "end_turn"),
        ]:
            state = ChatTranslationState()
            # Send initial + finish
            chat_chunk_to_anthropic_events({
                "model": "m",
                "choices": [{"delta": {"role": "assistant"}, "finish_reason": None}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }, state)
            events = chat_chunk_to_anthropic_events({
                "choices": [{"delta": {}, "finish_reason": cc_reason}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }, state)
            msg_deltas = [e for e in events if e["type"] == "message_delta"]
            assert msg_deltas[0]["delta"]["stop_reason"] == anth_reason

    def test_cached_tokens_subtracted(self):
        state = ChatTranslationState()
        events = chat_chunk_to_anthropic_events({
            "model": "m",
            "choices": [{"delta": {"role": "assistant"}, "finish_reason": None}],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 0,
                "prompt_tokens_details": {"cached_tokens": 300},
            },
        }, state)
        msg_start = events[0]
        assert msg_start["message"]["usage"]["input_tokens"] == 700
        assert msg_start["message"]["usage"]["cache_read_input_tokens"] == 300


# ─── Chat Completions URL + Headers ───────────────────────────────────────


class TestCopilotChatCompletionsUrl:
    def test_builds_chat_completions_url(self):
        assert copilot_chat_completions_url("https://api.individual.githubcopilot.com") == \
            "https://api.individual.githubcopilot.com/chat/completions"

    def test_strips_trailing_slash(self):
        assert copilot_chat_completions_url("https://example.com/") == \
            "https://example.com/chat/completions"


class TestCopilotChatHeaders:
    def test_user_initiator_for_first_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        headers = copilot_chat_headers(messages, "tok_123", 100)
        assert headers["X-Initiator"] == "user"
        assert headers["Authorization"] == "Bearer tok_123"

    def test_agent_initiator_for_multi_turn(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Run ls"},
        ]
        headers = copilot_chat_headers(messages, "tok_123", 100)
        assert headers["X-Initiator"] == "agent"

    def test_agent_initiator_for_tool_results(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "tool", "tool_call_id": "x", "content": "output"},
        ]
        headers = copilot_chat_headers(messages, "tok_123", 100)
        assert headers["X-Initiator"] == "agent"
