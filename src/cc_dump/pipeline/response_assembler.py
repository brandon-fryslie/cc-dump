"""Proxy-boundary SSE response assembler.

Reconstructs complete Claude API responses from SSE event fragments.
The assembler sits at the proxy boundary and produces immutable
complete-response records for downstream consumers.

// [LAW:one-source-of-truth] Canonical location for SSE→complete-message reconstruction.
// [LAW:single-enforcer] Assembly happens once, at the proxy boundary.

This module is STABLE — never hot-reloaded. Safe for `from` imports everywhere.
"""

import json
from dataclasses import dataclass, field
from typing import TypedDict

from cc_dump.pipeline.event_types import (
    ContentBlockStopEvent,
    InputJsonDeltaEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    SSEEvent,
    TextBlockStartEvent,
    TextDeltaEvent,
    ToolUseBlockStartEvent,
)


# ─── Types ───────────────────────────────────────────────────────────────────


class _UsageDict(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int


class _ContentBlock(TypedDict, total=False):
    type: str
    text: str
    id: str
    name: str
    input: dict


class ReconstructedMessage(TypedDict):
    id: str
    type: str
    role: str
    content: list[_ContentBlock]
    model: str
    stop_reason: str | None
    stop_sequence: str | None
    usage: _UsageDict


_SSEScalar = str | int | None
_SSEEventRecord = dict[str, _SSEScalar | dict[str, _SSEScalar | dict[str, _SSEScalar]]]


# ─── Reconstruction logic ────────────────────────────────────────────────────


class _ReconstructionState:
    """Shared state for event reconstructors."""

    def __init__(
        self,
        message: ReconstructedMessage,
        content_blocks: list,
        current_text_block: dict | None,
    ):
        self.message = message
        self.content_blocks = content_blocks
        self.current_text_block = current_text_block


def _handle_message_start(event: dict, state: _ReconstructionState) -> None:
    msg = event.get("message", {})
    state.message["id"] = msg.get("id", "")
    state.message["model"] = msg.get("model", "")
    state.message["role"] = msg.get("role", "assistant")
    state.message["usage"] = _extract_usage(msg.get("usage", {}))


def _extract_usage(raw_usage: dict) -> _UsageDict:
    usage: _UsageDict = {}
    if "input_tokens" in raw_usage:
        usage["input_tokens"] = raw_usage["input_tokens"]
    if "output_tokens" in raw_usage:
        usage["output_tokens"] = raw_usage["output_tokens"]
    if "cache_read_input_tokens" in raw_usage:
        usage["cache_read_input_tokens"] = raw_usage["cache_read_input_tokens"]
    if "cache_creation_input_tokens" in raw_usage:
        usage["cache_creation_input_tokens"] = raw_usage["cache_creation_input_tokens"]
    return usage


def _handle_content_block_start(event: dict, state: _ReconstructionState) -> None:
    block = event.get("content_block", {})
    block_type = block.get("type", "")
    if block_type == "text":
        state.current_text_block = {"type": "text", "text": ""}
        state.content_blocks.append(state.current_text_block)
    elif block_type == "tool_use":
        tool_block = {
            "type": "tool_use",
            "id": block.get("id", ""),
            "name": block.get("name", ""),
            "input": {},
        }
        state.content_blocks.append(tool_block)
        state.current_text_block = None


def _handle_content_block_delta(event: dict, state: _ReconstructionState) -> None:
    delta = event.get("delta", {})
    delta_type = delta.get("type", "")

    if delta_type == "text_delta" and state.current_text_block:
        state.current_text_block["text"] += delta.get("text", "")

    elif delta_type == "input_json_delta":
        if state.content_blocks and state.content_blocks[-1].get("type") == "tool_use":
            if "_input_json_str" not in state.content_blocks[-1]:
                state.content_blocks[-1]["_input_json_str"] = ""
            state.content_blocks[-1]["_input_json_str"] += delta.get(
                "partial_json", ""
            )


def _handle_content_block_stop(_event: dict, state: _ReconstructionState) -> None:
    if state.content_blocks and state.content_blocks[-1].get("type") == "tool_use":
        json_str = state.content_blocks[-1].pop("_input_json_str", "{}")
        try:
            state.content_blocks[-1]["input"] = json.loads(json_str)
        except json.JSONDecodeError:
            state.content_blocks[-1]["input"] = {}
    state.current_text_block = None


def _handle_message_delta(event: dict, state: _ReconstructionState) -> None:
    delta = event.get("delta", {})
    if "stop_reason" in delta:
        state.message["stop_reason"] = delta["stop_reason"]
    if "stop_sequence" in delta:
        state.message["stop_sequence"] = delta["stop_sequence"]
    usage_delta = event.get("usage", {})
    if usage_delta:
        state.message["usage"].update(usage_delta)


# [LAW:dataflow-not-control-flow] Event reconstruction dispatch table
_EVENT_RECONSTRUCTORS = {
    "message_start": _handle_message_start,
    "content_block_start": _handle_content_block_start,
    "content_block_delta": _handle_content_block_delta,
    "content_block_stop": _handle_content_block_stop,
    "message_delta": _handle_message_delta,
}


def reconstruct_message_from_events(
    events: list[_SSEEventRecord],
) -> ReconstructedMessage:
    """Reconstruct complete Claude message from SSE event sequence.

    Accumulates deltas into the same format as a stream=false API response.

    Args:
        events: List of SSE event dicts (message_start, content_block_delta, etc.)

    Returns:
        Complete message dict matching the Claude Messages API response shape.
    """
    message: ReconstructedMessage = {
        "id": "",
        "type": "message",
        "role": "assistant",
        "content": [],
        "model": "",
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {},
    }

    state = _ReconstructionState(
        message=message,
        content_blocks=[],
        current_text_block=None,
    )

    # [LAW:dataflow-not-control-flow] Dispatch via table lookup
    for event in events:
        event_type = event.get("type", "")
        handler = _EVENT_RECONSTRUCTORS.get(event_type)
        if handler:
            handler(event, state)

    state.message["content"] = state.content_blocks
    return state.message


# ─── Typed SSEEvent → raw dict bridge ────────────────────────────────────────


def sse_event_to_dict(sse_event: SSEEvent) -> _SSEEventRecord:
    """Convert a typed SSEEvent to the raw dict format used by reconstruction.

    Bridges from the typed event world (router/pipeline) to the raw dict
    world (reconstruction). Used by HAR recorder and other subscribers that
    need to feed typed events into reconstruct_message_from_events.
    """
    if isinstance(sse_event, MessageStartEvent):
        return {
            "type": "message_start",
            "message": {
                "id": sse_event.message.id,
                "type": "message",
                "role": sse_event.message.role.value,
                "model": sse_event.message.model,
                "usage": {
                    "input_tokens": sse_event.message.usage.input_tokens,
                    "output_tokens": sse_event.message.usage.output_tokens,
                    "cache_read_input_tokens": sse_event.message.usage.cache_read_input_tokens,
                    "cache_creation_input_tokens": sse_event.message.usage.cache_creation_input_tokens,
                },
            },
        }
    elif isinstance(sse_event, TextBlockStartEvent):
        return {
            "type": "content_block_start",
            "index": sse_event.index,
            "content_block": {"type": "text", "text": ""},
        }
    elif isinstance(sse_event, ToolUseBlockStartEvent):
        return {
            "type": "content_block_start",
            "index": sse_event.index,
            "content_block": {
                "type": "tool_use",
                "id": sse_event.id,
                "name": sse_event.name,
            },
        }
    elif isinstance(sse_event, TextDeltaEvent):
        return {
            "type": "content_block_delta",
            "index": sse_event.index,
            "delta": {"type": "text_delta", "text": sse_event.text},
        }
    elif isinstance(sse_event, InputJsonDeltaEvent):
        return {
            "type": "content_block_delta",
            "index": sse_event.index,
            "delta": {
                "type": "input_json_delta",
                "partial_json": sse_event.partial_json,
            },
        }
    elif isinstance(sse_event, ContentBlockStopEvent):
        return {
            "type": "content_block_stop",
            "index": sse_event.index,
        }
    elif isinstance(sse_event, MessageDeltaEvent):
        delta: dict[str, object] = {}
        if sse_event.stop_reason.value:
            delta["stop_reason"] = sse_event.stop_reason.value
        if sse_event.stop_sequence:
            delta["stop_sequence"] = sse_event.stop_sequence
        return {
            "type": "message_delta",
            "delta": delta,
            "usage": {"output_tokens": sse_event.output_tokens},
        }
    else:
        return {"type": "message_stop"}


# ─── ResponseAssembler ───────────────────────────────────────────────────────


class ResponseAssembler:
    """Assembles SSE fragments into a complete response at the proxy boundary.

    Implements the StreamSink protocol (on_raw, on_event, on_done) so it can
    be added to _fan_out_sse alongside ClientSink and EventQueueSink.

    After on_done(), the complete response is available via .result.
    The assembler does not interfere with live display — EventQueueSink still
    emits per-event for real-time TUI rendering.

    Usage::

        assembler = ResponseAssembler()
        _fan_out_sse(resp, [ClientSink(wfile), EventQueueSink(q), assembler])
        complete_message = assembler.result  # ReconstructedMessage or None
    """

    def __init__(self) -> None:
        self._events: list[_SSEEventRecord] = []
        self._result: ReconstructedMessage | None = None

    def on_raw(self, data: bytes) -> None:
        """No-op — raw bytes not needed for assembly."""

    def on_event(self, event_type: str, event: dict) -> None:
        """Accumulate an SSE event for reconstruction."""
        self._events.append(event)

    def on_done(self) -> None:
        """Reconstruct the complete message from accumulated events."""
        if self._events:
            self._result = reconstruct_message_from_events(self._events)

    @property
    def result(self) -> ReconstructedMessage | None:
        """The reconstructed complete message, or None if no events received."""
        return self._result


class OpenAiChatResponseAssembler:
    """Assembles OpenAI SSE fragments into a complete response dict.

    Accumulates text deltas and tool call fragments from OpenAI's streaming
    format into a dict that matches the OpenAI chat completion response shape.
    """

    def __init__(self) -> None:
        self._chunks: list[dict] = []
        self._result: dict | None = None

    def on_raw(self, data: bytes) -> None:
        pass

    def on_event(self, event_type: str, event: dict) -> None:
        self._chunks.append(event)

    def on_done(self) -> None:
        if not self._chunks:
            return
        self._result = _reconstruct_openai_chat_message(self._chunks)

    @property
    def result(self) -> dict | None:
        return self._result


@dataclass
class _OpenAiChatReconstructionState:
    """Canonical in-flight state for OpenAI chunk reconstruction.

    // [LAW:one-source-of-truth] All reconstruction state lives in one canonical value.
    """

    message_content_parts: list[str] = field(default_factory=list)
    model: str = ""
    message_id: str = ""
    finish_reason: str | None = None
    tool_calls: dict[int, dict] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)


def _merge_openai_chat_chunk_identity(
    chunk: dict,
    state: _OpenAiChatReconstructionState,
) -> None:
    if not state.message_id:
        state.message_id = str(chunk.get("id", "") or "")
    if not state.model:
        state.model = str(chunk.get("model", "") or "")


def _merge_openai_chat_chunk_usage(
    chunk: dict,
    state: _OpenAiChatReconstructionState,
) -> None:
    chunk_usage = chunk.get("usage")
    if not isinstance(chunk_usage, dict):
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in chunk_usage:
            state.usage[key] = chunk_usage[key]


def _merge_openai_chat_delta_content(
    delta: dict,
    state: _OpenAiChatReconstructionState,
) -> None:
    content = delta.get("content")
    if isinstance(content, str):
        state.message_content_parts.append(content)


def _openai_chat_tool_call_entry(
    tool_calls: dict[int, dict],
    index: int,
) -> dict:
    if index not in tool_calls:
        tool_calls[index] = {
            "id": "",
            "type": "function",
            "function": {"name": "", "arguments": ""},
        }
    return tool_calls[index]


def _openai_chat_tool_call_index(tool_call: dict) -> int:
    raw_index = tool_call.get("index", 0)
    return raw_index if isinstance(raw_index, int) else 0


def _openai_chat_tool_call_id(tool_call: dict) -> str:
    tool_call_id = tool_call.get("id")
    return tool_call_id if isinstance(tool_call_id, str) and tool_call_id else ""


def _openai_chat_tool_call_function(tool_call: dict) -> dict:
    func = tool_call.get("function", {})
    return func if isinstance(func, dict) else {}


def _merge_openai_chat_tool_function(entry_function: dict, source_function: dict) -> None:
    name = source_function.get("name")
    if isinstance(name, str) and name:
        entry_function["name"] = name
    arguments = source_function.get("arguments")
    if isinstance(arguments, str):
        entry_function["arguments"] += arguments


def _merge_openai_chat_tool_call(tool_call: dict, state: _OpenAiChatReconstructionState) -> None:
    index = _openai_chat_tool_call_index(tool_call)
    entry = _openai_chat_tool_call_entry(state.tool_calls, index)
    tool_call_id = _openai_chat_tool_call_id(tool_call)
    if tool_call_id:
        entry["id"] = tool_call_id
    _merge_openai_chat_tool_function(
        entry["function"],
        _openai_chat_tool_call_function(tool_call),
    )


def _merge_openai_chat_delta_tool_calls(
    delta: dict,
    state: _OpenAiChatReconstructionState,
) -> None:
    raw_tool_calls = delta.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return
    for tool_call in raw_tool_calls:
        if not isinstance(tool_call, dict):
            continue
        _merge_openai_chat_tool_call(tool_call, state)


# [LAW:dataflow-not-control-flow] Fixed-order reducers keep operation order constant per delta.
_OPENAI_CHAT_DELTA_REDUCERS = (
    _merge_openai_chat_delta_content,
    _merge_openai_chat_delta_tool_calls,
)


def _merge_openai_chat_choice(
    choice: dict,
    state: _OpenAiChatReconstructionState,
) -> None:
    finish_reason = choice.get("finish_reason")
    if isinstance(finish_reason, str) and finish_reason:
        state.finish_reason = finish_reason

    delta = choice.get("delta", {})
    if not isinstance(delta, dict):
        return
    for reducer in _OPENAI_CHAT_DELTA_REDUCERS:
        reducer(delta, state)


def _openai_chat_response_usage(state: _OpenAiChatReconstructionState) -> dict[str, int]:
    return state.usage or {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def _openai_chat_response_message(state: _OpenAiChatReconstructionState) -> dict:
    message_content = "".join(state.message_content_parts)
    result_message: dict = {"role": "assistant", "content": message_content or None}
    if state.tool_calls:
        result_message["tool_calls"] = [state.tool_calls[i] for i in sorted(state.tool_calls)]
    return result_message


def _reconstruct_openai_chat_message(chunks: list[dict]) -> dict:
    """Reconstruct a complete OpenAI chat completion from streaming chunks.

    Accumulates delta.content and delta.tool_calls into the non-streaming shape.
    """
    state = _OpenAiChatReconstructionState()

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        _merge_openai_chat_chunk_identity(chunk, state)
        _merge_openai_chat_chunk_usage(chunk, state)
        choices = chunk.get("choices", [])
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            _merge_openai_chat_choice(choice, state)

    return {
        "id": state.message_id,
        "object": "chat.completion",
        "model": state.model,
        "choices": [
            {
                "index": 0,
                "message": _openai_chat_response_message(state),
                "finish_reason": state.finish_reason,
            }
        ],
        "usage": _openai_chat_response_usage(state),
    }
