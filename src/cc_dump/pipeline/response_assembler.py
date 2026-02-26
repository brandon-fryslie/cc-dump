"""Proxy-boundary SSE response assembler.

Reconstructs complete Claude API responses from SSE event fragments.
The assembler sits at the proxy boundary and produces immutable
complete-response records for downstream consumers.

// [LAW:one-source-of-truth] Canonical location for SSE→complete-message reconstruction.
// [LAW:single-enforcer] Assembly happens once, at the proxy boundary.

This module is STABLE — never hot-reloaded. Safe for `from` imports everywhere.
"""

import json
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
    raw_usage = msg.get("usage", {})
    usage: _UsageDict = {}
    for k in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        if k in raw_usage:
            usage[k] = raw_usage[k]  # type: ignore[literal-required]
    state.message["usage"] = usage


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


class OpenAIResponseAssembler:
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
        self._result = _reconstruct_openai_message(self._chunks)

    @property
    def result(self) -> dict | None:
        return self._result


def _reconstruct_openai_message(chunks: list[dict]) -> dict:
    """Reconstruct a complete OpenAI chat completion from streaming chunks.

    Accumulates delta.content and delta.tool_calls into the non-streaming shape.
    """
    message_content = ""
    model = ""
    message_id = ""
    finish_reason = None
    tool_calls: dict[int, dict] = {}  # index → {id, type, function: {name, arguments}}
    usage: dict[str, int] = {}

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue

        if not message_id:
            message_id = str(chunk.get("id", "") or "")
        if not model:
            model = str(chunk.get("model", "") or "")

        # Usage from final chunk (OpenAI includes it when stream_options.include_usage=true)
        chunk_usage = chunk.get("usage")
        if isinstance(chunk_usage, dict):
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if k in chunk_usage:
                    usage[k] = chunk_usage[k]

        choices = chunk.get("choices", [])
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            fr = choice.get("finish_reason")
            if isinstance(fr, str) and fr:
                finish_reason = fr

            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                continue

            content = delta.get("content")
            if isinstance(content, str):
                message_content += content

            delta_tool_calls = delta.get("tool_calls")
            if isinstance(delta_tool_calls, list):
                for tc in delta_tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    idx = tc.get("index", 0)
                    if not isinstance(idx, int):
                        idx = 0
                    if idx not in tool_calls:
                        tool_calls[idx] = {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = tool_calls[idx]
                    tc_id = tc.get("id")
                    if isinstance(tc_id, str) and tc_id:
                        entry["id"] = tc_id
                    func = tc.get("function", {})
                    if isinstance(func, dict):
                        name = func.get("name")
                        if isinstance(name, str) and name:
                            entry["function"]["name"] = name
                        args = func.get("arguments")
                        if isinstance(args, str):
                            entry["function"]["arguments"] += args

    result_message: dict = {"role": "assistant", "content": message_content or None}
    if tool_calls:
        result_message["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]

    return {
        "id": message_id,
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": result_message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
