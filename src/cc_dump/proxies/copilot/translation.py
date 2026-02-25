"""Anthropic <-> OpenAI payload translation for Copilot upstreams.

General structure ported from the reference copilot-api project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


def map_openai_stop_reason_to_anthropic(reason: str | None) -> str:
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "stop_sequence",
    }
    return mapping.get(str(reason or ""), "end_turn")


def translate_model_name(model: str) -> str:
    model = str(model or "")
    if model.startswith("claude-sonnet-4-"):
        return "claude-sonnet-4"
    if model.startswith("claude-opus-4-"):
        return "claude-opus-4"
    return model


def _handle_system_prompt(system: object) -> list[dict[str, Any]]:
    if isinstance(system, str):
        return [{"role": "system", "content": system}]
    if isinstance(system, list):
        text_parts = [
            str(block.get("text", ""))
            for block in system
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        if text_parts:
            return [{"role": "system", "content": "\n\n".join(text_parts)}]
    return []


def _map_content(content: object) -> object:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None

    has_image = any(isinstance(block, dict) and block.get("type") == "image" for block in content)
    if not has_image:
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", ""))
            if block_type == "text" and isinstance(block.get("text"), str):
                text_parts.append(str(block.get("text")))
            elif block_type == "thinking" and isinstance(block.get("thinking"), str):
                text_parts.append(str(block.get("thinking")))
        return "\n\n".join(text_parts)

    mapped_parts: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type", ""))
        if block_type == "text" and isinstance(block.get("text"), str):
            mapped_parts.append({"type": "text", "text": block["text"]})
        elif block_type == "thinking" and isinstance(block.get("thinking"), str):
            mapped_parts.append({"type": "text", "text": block["thinking"]})
        elif block_type == "image":
            source = block.get("source", {})
            if not isinstance(source, dict):
                continue
            media_type = str(source.get("media_type", "image/png"))
            data = str(source.get("data", ""))
            mapped_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                }
            )
    return mapped_parts


def _handle_user_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content", "")
    if not isinstance(content, list):
        return [{"role": "user", "content": _map_content(content)}]

    tool_results: list[dict[str, Any]] = []
    other_blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            tool_results.append(block)
        else:
            other_blocks.append(block)

    messages: list[dict[str, Any]] = []
    for block in tool_results:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": str(block.get("tool_use_id", "")),
                "content": _map_content(block.get("content", "")),
            }
        )
    if other_blocks:
        messages.append({"role": "user", "content": _map_content(other_blocks)})
    return messages


def _handle_assistant_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content", "")
    if not isinstance(content, list):
        return [{"role": "assistant", "content": _map_content(content)}]

    tool_use_blocks = [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]
    text_blocks = [
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    thinking_blocks = [
        str(block.get("thinking", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "thinking"
    ]
    all_text = "\n\n".join([*text_blocks, *thinking_blocks]).strip()

    if tool_use_blocks:
        tool_calls: list[dict[str, Any]] = []
        for block in tool_use_blocks:
            tool_calls.append(
                {
                    "id": str(block.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name", "")),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                }
            )
        return [{"role": "assistant", "content": all_text or None, "tool_calls": tool_calls}]
    return [{"role": "assistant", "content": _map_content(content)}]


def _translate_anthropic_messages_to_openai(
    anthropic_messages: object,
    system: object,
) -> list[dict[str, Any]]:
    output = _handle_system_prompt(system)
    if not isinstance(anthropic_messages, list):
        return output

    for message in anthropic_messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", ""))
        if role == "user":
            output.extend(_handle_user_message(message))
        elif role == "assistant":
            output.extend(_handle_assistant_message(message))
    return output


def _translate_tools(anthropic_tools: object) -> list[dict[str, Any]] | None:
    if not isinstance(anthropic_tools, list):
        return None
    translated: list[dict[str, Any]] = []
    for tool in anthropic_tools:
        if not isinstance(tool, dict):
            continue
        translated.append(
            {
                "type": "function",
                "function": {
                    "name": str(tool.get("name", "")),
                    "description": str(tool.get("description", "")),
                    "parameters": tool.get("input_schema", {}),
                },
            }
        )
    return translated or None


def _translate_tool_choice(choice: object) -> object:
    if not isinstance(choice, dict):
        return None
    choice_type = str(choice.get("type", ""))
    if choice_type == "auto":
        return "auto"
    if choice_type == "any":
        return "required"
    if choice_type == "none":
        return "none"
    if choice_type == "tool":
        tool_name = str(choice.get("name", ""))
        if tool_name:
            return {"type": "function", "function": {"name": tool_name}}
    return None


def _drop_none_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


def translate_to_openai(payload: dict[str, Any]) -> dict[str, Any]:
    mapped = {
        "model": translate_model_name(str(payload.get("model", ""))),
        "messages": _translate_anthropic_messages_to_openai(
            payload.get("messages", []),
            payload.get("system"),
        ),
        "max_tokens": payload.get("max_tokens"),
        "stop": payload.get("stop_sequences"),
        "stream": payload.get("stream"),
        "temperature": payload.get("temperature"),
        "top_p": payload.get("top_p"),
        "user": payload.get("metadata", {}).get("user_id")
        if isinstance(payload.get("metadata"), dict)
        else None,
        "tools": _translate_tools(payload.get("tools")),
        "tool_choice": _translate_tool_choice(payload.get("tool_choice")),
    }
    return _drop_none_fields(mapped)


def _text_blocks_from_openai_content(content: object) -> list[dict[str, str]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return []
    blocks: list[dict[str, str]] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            blocks.append({"type": "text", "text": str(part["text"])})
    return blocks


def _tool_use_blocks_from_openai(tool_calls: object) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list):
        return []
    blocks: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        fn = tool_call.get("function", {})
        if not isinstance(fn, dict):
            fn = {}
        raw_args = fn.get("arguments", "{}")
        parsed_args: object
        try:
            parsed_args = json.loads(str(raw_args or "{}"))
        except json.JSONDecodeError:
            parsed_args = {}
        if not isinstance(parsed_args, dict):
            parsed_args = {}
        blocks.append(
            {
                "type": "tool_use",
                "id": str(tool_call.get("id", "")),
                "name": str(fn.get("name", "")),
                "input": parsed_args,
            }
        )
    return blocks


def translate_to_anthropic(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices", [])
    if not isinstance(choices, list):
        choices = []

    all_text_blocks: list[dict[str, Any]] = []
    all_tool_use_blocks: list[dict[str, Any]] = []
    stop_reason = "end_turn"
    for idx, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message", {})
        if not isinstance(message, dict):
            message = {}
        all_text_blocks.extend(_text_blocks_from_openai_content(message.get("content")))
        all_tool_use_blocks.extend(_tool_use_blocks_from_openai(message.get("tool_calls")))
        current_finish = map_openai_stop_reason_to_anthropic(str(choice.get("finish_reason", "")))
        if idx == 0 or current_finish == "tool_use":
            stop_reason = current_finish

    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    details = usage.get("prompt_tokens_details", {})
    if not isinstance(details, dict):
        details = {}
    cached_tokens = int(details.get("cached_tokens", 0) or 0)

    usage_out = {
        "input_tokens": max(0, prompt_tokens - cached_tokens),
        "output_tokens": completion_tokens,
    }
    if cached_tokens:
        usage_out["cache_read_input_tokens"] = cached_tokens

    return {
        "id": str(response.get("id", "")),
        "type": "message",
        "role": "assistant",
        "model": str(response.get("model", "")),
        "content": [*all_text_blocks, *all_tool_use_blocks],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage_out,
    }


def translate_models_to_anthropic(copilot_models: dict[str, Any]) -> dict[str, Any]:
    raw_data = copilot_models.get("data", [])
    if not isinstance(raw_data, list):
        raw_data = []

    translated_data: list[dict[str, Any]] = []
    for model in raw_data:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id", "")).strip()
        if not model_id:
            continue
        display_name = str(model.get("name", "")).strip() or model_id
        translated_data.append(
            {
                "type": "model",
                "id": model_id,
                "display_name": display_name,
                "created_at": "1970-01-01T00:00:00Z",
            }
        )

    first_id = translated_data[0]["id"] if translated_data else ""
    last_id = translated_data[-1]["id"] if translated_data else ""
    return {
        "data": translated_data,
        "has_more": False,
        "first_id": first_id,
        "last_id": last_id,
    }


def translate_error_to_anthropic(
    error_payload: dict[str, Any],
    *,
    fallback_message: str = "Upstream provider error",
) -> dict[str, Any]:
    error = error_payload.get("error", {})
    if not isinstance(error, dict):
        error = {}
    message = str(error.get("message", "") or "").strip() or fallback_message
    raw_type = str(error.get("type", "") or "").strip()
    mapped_type = raw_type or "api_error"
    return {
        "type": "error",
        "error": {
            "type": mapped_type,
            "message": message,
        },
    }


def translate_stream_error_to_anthropic() -> dict[str, Any]:
    return {
        "type": "error",
        "error": {
            "type": "api_error",
            "message": "An unexpected error occurred during streaming.",
        },
    }


@dataclass
class ToolCallState:
    id: str
    name: str
    anthropic_block_index: int


@dataclass
class AnthropicStreamState:
    message_start_sent: bool = False
    content_block_index: int = 0
    content_block_open: bool = False
    tool_calls: dict[int, ToolCallState] = field(default_factory=dict)


def _is_tool_block_open(state: AnthropicStreamState) -> bool:
    if not state.content_block_open:
        return False
    return any(
        tc.anthropic_block_index == state.content_block_index
        for tc in state.tool_calls.values()
    )


def _usage_from_chunk(chunk: dict[str, Any]) -> tuple[int, int, int]:
    usage = chunk.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    details = usage.get("prompt_tokens_details", {})
    if not isinstance(details, dict):
        details = {}
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    cached_tokens = int(details.get("cached_tokens", 0) or 0)
    return prompt_tokens, completion_tokens, cached_tokens


def translate_chunk_to_anthropic_events(
    chunk: dict[str, Any],
    state: AnthropicStreamState,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    choices = chunk.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return events

    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta", {})
    if not isinstance(delta, dict):
        delta = {}

    prompt_tokens, completion_tokens, cached_tokens = _usage_from_chunk(chunk)

    if not state.message_start_sent:
        usage = {
            "input_tokens": max(0, prompt_tokens - cached_tokens),
            "output_tokens": 0,
        }
        if cached_tokens:
            usage["cache_read_input_tokens"] = cached_tokens
        events.append(
            {
                "type": "message_start",
                "message": {
                    "id": str(chunk.get("id", "")),
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": str(chunk.get("model", "")),
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": usage,
                },
            }
        )
        state.message_start_sent = True

    content_delta = delta.get("content")
    if isinstance(content_delta, str) and content_delta:
        if _is_tool_block_open(state):
            events.append(
                {
                    "type": "content_block_stop",
                    "index": state.content_block_index,
                }
            )
            state.content_block_index += 1
            state.content_block_open = False

        if not state.content_block_open:
            events.append(
                {
                    "type": "content_block_start",
                    "index": state.content_block_index,
                    "content_block": {"type": "text", "text": ""},
                }
            )
            state.content_block_open = True

        events.append(
            {
                "type": "content_block_delta",
                "index": state.content_block_index,
                "delta": {"type": "text_delta", "text": content_delta},
            }
        )

    tool_calls = delta.get("tool_calls", [])
    if isinstance(tool_calls, list):
        for raw_tool_call in tool_calls:
            if not isinstance(raw_tool_call, dict):
                continue
            raw_index = raw_tool_call.get("index", 0)
            try:
                tool_index = int(raw_index)
            except (TypeError, ValueError):
                tool_index = 0
            fn = raw_tool_call.get("function", {})
            if not isinstance(fn, dict):
                fn = {}
            tool_id = raw_tool_call.get("id")
            tool_name = fn.get("name")
            if isinstance(tool_id, str) and tool_id and isinstance(tool_name, str) and tool_name:
                if state.content_block_open:
                    events.append(
                        {
                            "type": "content_block_stop",
                            "index": state.content_block_index,
                        }
                    )
                    state.content_block_index += 1
                    state.content_block_open = False

                block_index = state.content_block_index
                state.tool_calls[tool_index] = ToolCallState(
                    id=tool_id,
                    name=tool_name,
                    anthropic_block_index=block_index,
                )
                events.append(
                    {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": tool_name,
                            "input": {},
                        },
                    }
                )
                state.content_block_open = True

            arguments = fn.get("arguments")
            tool_info = state.tool_calls.get(tool_index)
            if isinstance(arguments, str) and arguments and tool_info is not None:
                events.append(
                    {
                        "type": "content_block_delta",
                        "index": tool_info.anthropic_block_index,
                        "delta": {"type": "input_json_delta", "partial_json": arguments},
                    }
                )

    finish_reason = choice.get("finish_reason")
    if finish_reason:
        if state.content_block_open:
            events.append(
                {
                    "type": "content_block_stop",
                    "index": state.content_block_index,
                }
            )
            state.content_block_open = False

        usage = {
            "input_tokens": max(0, prompt_tokens - cached_tokens),
            "output_tokens": completion_tokens,
        }
        if cached_tokens:
            usage["cache_read_input_tokens"] = cached_tokens

        events.extend(
            [
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": map_openai_stop_reason_to_anthropic(str(finish_reason)),
                        "stop_sequence": None,
                    },
                    "usage": usage,
                },
                {"type": "message_stop"},
            ]
        )

    return events
