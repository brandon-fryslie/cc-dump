from cc_dump.proxies.copilot.translation import (
    AnthropicStreamState,
    translate_chunk_to_anthropic_events,
    translate_error_to_anthropic,
    translate_models_to_anthropic,
    translate_stream_error_to_anthropic,
    translate_to_anthropic,
    translate_to_openai,
)


def test_translate_to_openai_maps_model_and_messages():
    anthropic_payload = {
        "model": "claude-sonnet-4-20251001",
        "system": [{"type": "text", "text": "sys-a"}, {"type": "text", "text": "sys-b"}],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hello"}],
            }
        ],
        "stream": True,
        "tools": [
            {
                "name": "Read",
                "description": "Read file",
                "input_schema": {"type": "object"},
            }
        ],
    }
    openai_payload = translate_to_openai(anthropic_payload)
    assert openai_payload["model"] == "claude-sonnet-4"
    assert openai_payload["messages"][0] == {"role": "system", "content": "sys-a\n\nsys-b"}
    assert openai_payload["messages"][1] == {"role": "user", "content": "hello"}
    assert openai_payload["tools"][0]["function"]["name"] == "Read"


def test_translate_to_anthropic_maps_usage_and_tool_calls():
    openai_response = {
        "id": "chatcmpl_123",
        "model": "claude-sonnet-4",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "Done",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "Read", "arguments": '{"path":"x.py"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 7,
            "prompt_tokens_details": {"cached_tokens": 20},
        },
    }
    anthropic_response = translate_to_anthropic(openai_response)
    assert anthropic_response["id"] == "chatcmpl_123"
    assert anthropic_response["stop_reason"] == "tool_use"
    assert anthropic_response["usage"]["input_tokens"] == 80
    assert anthropic_response["usage"]["cache_read_input_tokens"] == 20
    assert anthropic_response["usage"]["output_tokens"] == 7
    assert anthropic_response["content"][0] == {"type": "text", "text": "Done"}
    assert anthropic_response["content"][1]["type"] == "tool_use"
    assert anthropic_response["content"][1]["input"] == {"path": "x.py"}


def test_translate_chunk_to_anthropic_events_emits_message_start_and_stop():
    state = AnthropicStreamState()
    first_chunk = {
        "id": "chunk_1",
        "model": "claude-sonnet-4",
        "choices": [{"delta": {"content": "hello "}, "finish_reason": None}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 0},
    }
    first_events = translate_chunk_to_anthropic_events(first_chunk, state)
    first_types = [event["type"] for event in first_events]
    assert first_types == ["message_start", "content_block_start", "content_block_delta"]
    assert first_events[0]["message"]["usage"]["input_tokens"] == 50

    end_chunk = {
        "id": "chunk_1",
        "model": "claude-sonnet-4",
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 3},
    }
    end_events = translate_chunk_to_anthropic_events(end_chunk, state)
    end_types = [event["type"] for event in end_events]
    assert end_types == ["content_block_stop", "message_delta", "message_stop"]
    assert end_events[1]["delta"]["stop_reason"] == "end_turn"
    assert end_events[1]["usage"]["output_tokens"] == 3


def test_translate_models_to_anthropic_shape():
    copilot_models = {
        "object": "list",
        "data": [
            {"id": "claude-sonnet-4", "name": "Claude Sonnet 4"},
            {"id": "gpt-4.1", "name": "GPT-4.1"},
        ],
    }
    translated = translate_models_to_anthropic(copilot_models)
    assert translated["has_more"] is False
    assert translated["first_id"] == "claude-sonnet-4"
    assert translated["last_id"] == "gpt-4.1"
    assert translated["data"][0]["type"] == "model"
    assert translated["data"][0]["display_name"] == "Claude Sonnet 4"


def test_translate_error_to_anthropic_shape():
    translated = translate_error_to_anthropic(
        {"error": {"type": "invalid_request_error", "message": "bad input"}},
        fallback_message="fallback",
    )
    assert translated == {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "bad input",
        },
    }


def test_translate_stream_error_to_anthropic_shape():
    translated = translate_stream_error_to_anthropic()
    assert translated == {
        "type": "error",
        "error": {
            "type": "api_error",
            "message": "An unexpected error occurred during streaming.",
        },
    }
