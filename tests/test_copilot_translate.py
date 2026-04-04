"""Tests for Anthropic ↔ Copilot (OpenAI Responses API) translation."""

import json
import pytest

from cc_dump.pipeline.copilot_translate import (
    anthropic_to_copilot_request,
    copilot_sse_to_anthropic_events,
    CopilotSSEParser,
    TranslationState,
    anthropic_sse_line,
    copilot_upstream_url,
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
            ("claude-sonnet-4-20250514", "claude-sonnet-4"),
            ("claude-opus-4-20250514", "claude-opus-4"),
            ("claude-haiku-3.5-20241022", "claude-haiku-3.5"),
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
