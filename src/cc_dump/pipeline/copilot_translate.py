"""Bidirectional translation between Anthropic Messages API and OpenAI Responses API.

When the Anthropic provider's upstream target is a Copilot host, the proxy activates
translation automatically. The upstream URL is the single source of truth — no flags,
no separate provider entry.

// [LAW:one-source-of-truth] All Anthropic↔Copilot format mapping lives here.
// [LAW:single-enforcer] Translation boundary — proxy.py never contains format knowledge.
// [LAW:dataflow-not-control-flow] Translation functions are pure data transforms.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import re

logger = logging.getLogger(__name__)


# ─── Constants ──────────────────────────────────────────────────────────────

_TOKEN_PATH = Path.home() / ".local" / "share" / "copilot-api" / "github_token"

# Strip dated suffixes like -20250514, -20251001 from model names.
_DATED_SUFFIX_RE = re.compile(r"-\d{8,}$")

# Anthropic model IDs → Copilot model IDs.
# Copilot uses dotted short names (claude-sonnet-4.6); Anthropic uses dashed
# or dated names (claude-sonnet-4-6, claude-haiku-4-5-20251001).
# // [LAW:one-source-of-truth] Model name translation lives here only.
_MODEL_MAP: dict[str, str] = {
    # Current generation — dashed → dotted
    "claude-sonnet-4-6": "claude-sonnet-4.6",
    "claude-opus-4-6": "claude-opus-4.6",
    "claude-opus-4-6-fast": "claude-opus-4.6-fast",
    "claude-haiku-4-5": "claude-haiku-4.5",
    "claude-sonnet-4-5": "claude-sonnet-4.5",
    "claude-opus-4-5": "claude-opus-4.5",
    # Older generation
    "claude-sonnet-4": "claude-sonnet-4",
    "claude-opus-4": "claude-opus-4",
}

_DEFAULT_COPILOT_MODEL = "claude-sonnet-4.6"


def _map_model(raw: str) -> str:
    """Map Anthropic model name to Copilot model name.

    Strategy: try exact match first, then strip dated suffix and retry.
    // [LAW:one-source-of-truth] Model resolution logic lives here only.
    """
    result = _MODEL_MAP.get(raw)
    if result is not None:
        return result
    # Strip dated suffix (e.g. claude-haiku-4-5-20251001 → claude-haiku-4-5)
    stripped = _DATED_SUFFIX_RE.sub("", raw)
    result = _MODEL_MAP.get(stripped)
    if result is not None:
        return result
    # Pass through unknown models as-is
    return raw

# Required Copilot request headers
_COPILOT_HEADERS: dict[str, str] = {
    "Copilot-Integration-Id": "vscode-chat",
    "X-GitHub-Api-Version": "2025-05-01",
    "Openai-Intent": "conversation-panel",
    "Editor-Version": "vscode/1.100.0",
}


# ─── Auth ───────────────────────────────────────────────────────────────────


def read_copilot_token(path: Path = _TOKEN_PATH) -> str:
    """Read GitHub Copilot OAuth token from disk.

    // [LAW:single-enforcer] Token reading happens at this boundary.
    """
    text = path.read_text().strip()
    return text


# ─── Request Translation: Anthropic → Copilot (OpenAI Responses API) ──────


def anthropic_to_copilot_request(body: dict) -> dict:
    """Translate Anthropic Messages API request body to OpenAI Responses API format.

    // [LAW:dataflow-not-control-flow] Pure transform — every field is mapped unconditionally.
    """
    result: dict = {}

    # Model
    raw_model = body.get("model", "")
    result["model"] = _map_model(raw_model) if isinstance(raw_model, str) else _DEFAULT_COPILOT_MODEL

    # System prompt: Anthropic top-level "system" → Responses API "instructions"
    result["instructions"] = _translate_system(body.get("system"))

    # Messages → input items
    result["input"] = _translate_messages(body.get("messages", []))

    # Tools
    result["tools"] = _translate_tools(body.get("tools", []))

    # Streaming
    result["stream"] = body.get("stream", True)

    # Max tokens
    max_tokens = body.get("max_tokens")
    result["max_output_tokens"] = max_tokens if isinstance(max_tokens, int) else None

    # Copilot-specific fields
    result["store"] = False

    return result


def _translate_system(system: object) -> str:
    """Translate Anthropic system field to plain text instructions.

    Anthropic system can be: string, list of content blocks, or None.
    """
    # // [LAW:dataflow-not-control-flow] All three shapes handled by dispatch, not guards.
    translators = {
        str: lambda s: s,
        list: _system_blocks_to_text,
    }
    translator = translators.get(type(system), lambda _: "")
    return translator(system)


def _system_blocks_to_text(blocks: list) -> str:
    """Extract text from Anthropic system content blocks."""
    parts = [
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n\n".join(parts)


def _translate_messages(messages: list) -> list[dict]:
    """Translate Anthropic messages array to Responses API input array.

    Each Anthropic message becomes one or more input items.
    """
    items: list[dict] = []
    for msg in messages:
        items.extend(_translate_one_message(msg))
    return items


def _translate_one_message(msg: dict) -> list[dict]:
    """Translate a single Anthropic message to Responses API input item(s).

    An assistant message with tool_use blocks becomes:
      - a message item for text content
      - a function_call item per tool_use block

    A user message with tool_result blocks becomes:
      - function_call_output items per tool_result
      - a message item for any text content
    """
    role = msg.get("role", "user")
    content = msg.get("content", "")

    # String content → single message item
    content_blocks = (
        [{"type": "text", "text": content}]
        if isinstance(content, str)
        else content if isinstance(content, list)
        else []
    )

    items: list[dict] = []
    text_parts: list[str] = []

    for block in content_blocks:
        block_type = block.get("type", "") if isinstance(block, dict) else ""
        translator = _BLOCK_TRANSLATORS.get((role, block_type), _collect_text_block)
        translator(block, items, text_parts, role)

    # Flush accumulated text
    _flush_text(text_parts, items, role)
    return items


def _collect_text_block(
    block: dict,
    items: list[dict],
    text_parts: list[str],
    role: str,
) -> None:
    """Accumulate text content for later flushing as a single message item."""
    text = block.get("text", "")
    if isinstance(text, str) and text:
        text_parts.append(text)


def _translate_tool_use_block(
    block: dict,
    items: list[dict],
    text_parts: list[str],
    role: str,
) -> None:
    """Translate Anthropic tool_use block to Responses API function_call item."""
    # Flush any preceding text before the function call
    _flush_text(text_parts, items, role)
    tool_input = block.get("input", {})
    items.append({
        "type": "function_call",
        "name": block.get("name", ""),
        "call_id": block.get("id", ""),
        "arguments": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input),
    })


def _translate_tool_result_block(
    block: dict,
    items: list[dict],
    text_parts: list[str],
    role: str,
) -> None:
    """Translate Anthropic tool_result block to Responses API function_call_output item."""
    output = _extract_tool_result_text(block.get("content"))
    items.append({
        "type": "function_call_output",
        "call_id": block.get("tool_use_id", ""),
        "output": output,
    })


def _extract_tool_result_text(content: object) -> str:
    """Extract text from tool_result content (string or content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(parts)
    return ""


# // [LAW:dataflow-not-control-flow] Dispatch table keyed by (role, block_type).
_BLOCK_TRANSLATORS: dict[tuple[str, str], object] = {
    ("assistant", "tool_use"): _translate_tool_use_block,
    ("user", "tool_result"): _translate_tool_result_block,
}


def _flush_text(
    text_parts: list[str],
    items: list[dict],
    role: str,
) -> None:
    """Emit accumulated text parts as a single message input item, then clear."""
    combined = "\n".join(text_parts)
    text_parts.clear()
    # // [LAW:dataflow-not-control-flow] Always build the item; content may be empty string.
    # But only append if there's actual text — empty text messages are noise.
    if not combined:
        return
    content_type = "input_text" if role == "user" else "output_text"
    items.append({
        "type": "message",
        "role": role,
        "content": [{"type": content_type, "text": combined}],
    })


def _translate_tools(tools: list) -> list[dict]:
    """Translate Anthropic tool definitions to OpenAI function tool format."""
    return [_translate_one_tool(t) for t in tools if isinstance(t, dict)]


def _translate_one_tool(tool: dict) -> dict:
    """Translate one Anthropic tool definition.

    Anthropic: {name, description, input_schema: {type:"object", properties, required}}
    OpenAI:    {type:"function", name, description, parameters: {type:"object", properties, required}}
    """
    return {
        "type": "function",
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema", {}),
    }


def _translate_chat_tools(tools: list) -> list[dict]:
    """Translate Anthropic tool definitions to Chat Completions nested format.

    Chat Completions: {type:"function", function: {name, description, parameters}}
    // [LAW:one-source-of-truth] Chat Completions tool format lives here.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
        if isinstance(t, dict)
    ]


# ─── Response Translation: Copilot SSE → Anthropic SSE ─────────────────────

# The Copilot Responses API uses two-line SSE format:
#   event: response.created
#   data: {"response": {...}}
#
# Anthropic uses single-line with type embedded in JSON:
#   data: {"type": "message_start", "message": {...}}


@dataclass
class TranslationState:
    """Tracks state during SSE response translation.

    // [LAW:one-source-of-truth] Block index and item tracking state lives here.
    """
    message_id: str = field(default_factory=lambda: "msg_" + uuid.uuid4().hex[:12])
    block_index: int = 0
    # item_id → block_index mapping for correlating deltas to blocks
    item_blocks: dict[str, int] = field(default_factory=dict)
    # item_id → item metadata (name, call_id, type)
    item_meta: dict[str, dict] = field(default_factory=dict)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def copilot_sse_to_anthropic_events(
    event_type: str,
    data: dict,
    state: TranslationState,
) -> list[dict]:
    """Translate one Copilot SSE event into zero or more Anthropic SSE event dicts.

    Each returned dict is a complete Anthropic SSE event ready for JSON serialization.
    // [LAW:dataflow-not-control-flow] Dispatch table, not if/elif chain.
    """
    handler = _COPILOT_EVENT_HANDLERS.get(event_type, _handle_unknown)
    return handler(data, state)


def _handle_response_created(data: dict, state: TranslationState) -> list[dict]:
    """response.created → message_start"""
    response = data.get("response", {})
    state.model = response.get("model", "copilot")
    return [{
        "type": "message_start",
        "message": {
            "id": state.message_id,
            "type": "message",
            "role": "assistant",
            "model": state.model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }]


def _handle_output_item_added(data: dict, state: TranslationState) -> list[dict]:
    """response.output_item.added → content_block_start (for text and tool_use)"""
    item = data.get("item", {})
    item_type = item.get("type", "")
    item_id = item.get("id", "")

    # Skip reasoning blocks (deferred)
    # // [LAW:dataflow-not-control-flow] Reasoning items produce empty event list,
    # not a conditional skip.
    handler = _OUTPUT_ITEM_HANDLERS.get(item_type, lambda _i, _d, _s: [])
    return handler(item, item_id, state)


def _handle_message_item_added(item: dict, item_id: str, state: TranslationState) -> list[dict]:
    """Handle output_item.added for type=message → content_block_start(text)"""
    idx = state.block_index
    state.item_blocks[item_id] = idx
    state.item_meta[item_id] = {"type": "text"}
    state.block_index += 1
    return [{
        "type": "content_block_start",
        "index": idx,
        "content_block": {"type": "text", "text": ""},
    }]


def _handle_function_call_item_added(item: dict, item_id: str, state: TranslationState) -> list[dict]:
    """Handle output_item.added for type=function_call → content_block_start(tool_use)"""
    idx = state.block_index
    call_id = item.get("call_id", "")
    name = item.get("name", "")
    state.item_blocks[item_id] = idx
    state.item_meta[item_id] = {"type": "tool_use", "call_id": call_id, "name": name}
    state.block_index += 1
    return [{
        "type": "content_block_start",
        "index": idx,
        "content_block": {
            "type": "tool_use",
            "id": call_id,
            "name": name,
            "input": {},
        },
    }]


_OUTPUT_ITEM_HANDLERS: dict[str, object] = {
    "message": _handle_message_item_added,
    "function_call": _handle_function_call_item_added,
}


def _handle_output_text_delta(data: dict, state: TranslationState) -> list[dict]:
    """response.output_text.delta → content_block_delta(text_delta)"""
    item_id = data.get("item_id", "")
    idx = state.item_blocks.get(item_id, 0)
    delta_text = data.get("delta", "")
    return [{
        "type": "content_block_delta",
        "index": idx,
        "delta": {"type": "text_delta", "text": delta_text},
    }]


def _handle_function_call_args_delta(data: dict, state: TranslationState) -> list[dict]:
    """response.function_call_arguments.delta → content_block_delta(input_json_delta)"""
    item_id = data.get("item_id", "")
    idx = state.item_blocks.get(item_id, 0)
    delta_json = data.get("delta", "")
    return [{
        "type": "content_block_delta",
        "index": idx,
        "delta": {"type": "input_json_delta", "partial_json": delta_json},
    }]


def _handle_output_item_done(data: dict, state: TranslationState) -> list[dict]:
    """response.output_item.done → content_block_stop"""
    item = data.get("item", {})
    item_id = item.get("id", "")

    # Only emit stop for items we started blocks for
    idx = state.item_blocks.get(item_id)
    if idx is None:
        return []
    return [{"type": "content_block_stop", "index": idx}]


def _handle_response_completed(data: dict, state: TranslationState) -> list[dict]:
    """response.completed → message_delta + message_stop"""
    response = data.get("response", {})
    usage = response.get("usage", {})

    state.input_tokens = usage.get("input_tokens", 0)
    state.output_tokens = usage.get("output_tokens", 0)

    return [
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": state.output_tokens},
        },
        {"type": "message_stop"},
    ]


def _handle_unknown(data: dict, state: TranslationState) -> list[dict]:
    """Unknown event types produce no output."""
    return []


# // [LAW:dataflow-not-control-flow] Event type → handler dispatch table.
_COPILOT_EVENT_HANDLERS: dict[str, object] = {
    "response.created": _handle_response_created,
    "response.in_progress": _handle_unknown,  # no Anthropic equivalent
    "response.output_item.added": _handle_output_item_added,
    "response.output_text.delta": _handle_output_text_delta,
    "response.output_text.done": _handle_unknown,  # redundant with output_item.done
    "response.function_call_arguments.delta": _handle_function_call_args_delta,
    "response.function_call_arguments.done": _handle_unknown,  # redundant
    "response.output_item.done": _handle_output_item_done,
    "response.completed": _handle_response_completed,
}


# ─── SSE Byte-Level Translation ─────────────────────────────────────────────


def anthropic_sse_line(event: dict) -> bytes:
    """Format a single Anthropic SSE data line.

    // [LAW:one-source-of-truth] Anthropic SSE uses type-in-body format:
    // data: {"type": "...", ...}
    """
    return b"event: " + event["type"].encode() + b"\ndata: " + json.dumps(event).encode() + b"\n\n"


@dataclass
class CopilotSSEParser:
    """Accumulates raw SSE bytes and yields parsed (event_type, data_dict) pairs.

    OpenAI Responses API uses two-line SSE:
      event: response.created
      data: {"response": {...}}

    // [LAW:one-source-of-truth] SSE framing for Copilot protocol parsed here only.
    """
    _current_event: str = ""
    _current_data: list[str] = field(default_factory=list)
    _line_buffer: str = ""

    def feed(self, raw: bytes) -> list[tuple[str, dict]]:
        """Feed raw bytes, return completed (event_type, data) pairs."""
        self._line_buffer += raw.decode("utf-8", errors="replace")
        results: list[tuple[str, dict]] = []

        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            line = line.rstrip("\r")

            parsed = self._process_line(line)
            if parsed is not None:
                results.append(parsed)

        return results

    def _process_line(self, line: str) -> tuple[str, dict] | None:
        """Process one SSE line. Returns completed event or None."""
        if line.startswith("event: "):
            self._current_event = line[7:]
            return None

        if line.startswith("data: "):
            self._current_data.append(line[6:])
            return None

        # Empty line = end of event
        if line == "" and (self._current_event or self._current_data):
            event_type = self._current_event
            data_str = "\n".join(self._current_data)
            self._current_event = ""
            self._current_data = []

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                return None
            return (event_type, data)

        return None


# ─── Upstream URL + Headers ─────────────────────────────────────────────────


def copilot_upstream_url(base_url: str) -> str:
    """Build the Copilot Responses API URL.

    // [LAW:one-source-of-truth] Endpoint path lives here, not scattered in proxy.py.
    """
    return base_url.rstrip("/") + "/responses"


def copilot_upstream_headers(
    original_headers: dict[str, str],
    token: str,
    content_length: int,
) -> dict[str, str]:
    """Build headers for the Copilot upstream request.

    Drops Anthropic-specific headers, adds Copilot-required headers.
    // [LAW:single-enforcer] Header translation boundary.
    """
    # Start with a clean set — don't forward Anthropic headers
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Length": str(content_length),
    }
    headers.update(_COPILOT_HEADERS)
    return headers


# ─── Chat Completions Translation: Anthropic → OpenAI Chat Completions ─────
#
# Used when upstream_format == "openai-chat" (Copilot's Claude models).
# The Responses API translation above is for upstream_format == "openai-responses".
#
# // [LAW:one-source-of-truth] All Chat Completions format mapping lives in this section.


def anthropic_to_chat_completions_request(body: dict) -> dict:
    """Translate Anthropic Messages API request to OpenAI Chat Completions format.

    // [LAW:dataflow-not-control-flow] Pure transform — every field mapped unconditionally.
    """
    raw_model = body.get("model", "")
    model = _map_model(raw_model) if isinstance(raw_model, str) else _DEFAULT_COPILOT_MODEL

    messages: list[dict] = []

    # System prompt → system message
    system_text = _translate_system(body.get("system"))
    if system_text:
        messages.append({"role": "system", "content": system_text})

    # Anthropic messages → Chat Completions messages
    for msg in body.get("messages", []):
        messages.extend(_chat_translate_one_message(msg))

    result: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": body.get("max_tokens"),
        "stream": body.get("stream", True),
        "store": False,
    }

    # Optional fields — pass through when present
    temperature = body.get("temperature")
    if temperature is not None:
        result["temperature"] = temperature
    top_p = body.get("top_p")
    if top_p is not None:
        result["top_p"] = top_p
    stop = body.get("stop_sequences")
    if stop is not None:
        result["stop"] = stop

    # Tools — Chat Completions uses nested {type, function: {name, desc, parameters}}
    tools = body.get("tools")
    if tools:
        result["tools"] = _translate_chat_tools(tools)

    # Tool choice
    tool_choice = body.get("tool_choice")
    if tool_choice is not None:
        result["tool_choice"] = _translate_tool_choice(tool_choice)

    return result


def _chat_translate_one_message(msg: dict) -> list[dict]:
    """Translate one Anthropic message to Chat Completions message(s).

    An assistant message with tool_use blocks becomes one message with tool_calls.
    A user message with tool_result blocks becomes tool-role messages.
    """
    role = msg.get("role", "user")
    content = msg.get("content", "")

    # String content — single message
    if isinstance(content, str):
        return [{"role": role, "content": content}]

    content_blocks = content if isinstance(content, list) else []

    # // [LAW:dataflow-not-control-flow] Role → handler dispatch.
    handler = _CHAT_MSG_HANDLERS.get(role, _chat_handle_generic_message)
    return handler(role, content_blocks)


def _chat_handle_user_message(role: str, blocks: list) -> list[dict]:
    """User message: extract tool_results as tool messages, rest as user content."""
    messages: list[dict] = []
    text_parts: list[str] = []

    for block in blocks:
        block_type = block.get("type", "") if isinstance(block, dict) else ""
        if block_type == "tool_result":
            # Flush text before tool result
            if text_parts:
                messages.append({"role": "user", "content": "\n".join(text_parts)})
                text_parts.clear()
            output = _extract_tool_result_text(block.get("content"))
            messages.append({
                "role": "tool",
                "tool_call_id": block.get("tool_use_id", ""),
                "content": output,
            })
        elif block_type == "text":
            text = block.get("text", "")
            if text:
                text_parts.append(text)

    if text_parts:
        messages.append({"role": "user", "content": "\n".join(text_parts)})

    return messages


def _chat_handle_assistant_message(role: str, blocks: list) -> list[dict]:
    """Assistant message: text + tool_use blocks → single message with tool_calls."""
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in blocks:
        block_type = block.get("type", "") if isinstance(block, dict) else ""
        if block_type == "tool_use":
            tool_input = block.get("input", {})
            tool_calls.append({
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input),
                },
            })
        elif block_type == "text":
            text = block.get("text", "")
            if text:
                text_parts.append(text)
        elif block_type == "thinking":
            # Fold thinking into text (Chat Completions has no thinking blocks)
            text = block.get("thinking", "")
            if text:
                text_parts.append(text)

    combined_text = "\n\n".join(text_parts) if text_parts else None

    msg: dict = {"role": "assistant", "content": combined_text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return [msg]


def _chat_handle_generic_message(role: str, blocks: list) -> list[dict]:
    """Fallback: concatenate text blocks."""
    parts = [
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return [{"role": role, "content": "\n".join(parts)}]


# // [LAW:dataflow-not-control-flow] Role → message handler dispatch.
_CHAT_MSG_HANDLERS: dict[str, object] = {
    "user": _chat_handle_user_message,
    "assistant": _chat_handle_assistant_message,
}


def _translate_tool_choice(tool_choice: object) -> object:
    """Translate Anthropic tool_choice to Chat Completions format."""
    if not isinstance(tool_choice, dict):
        return None
    tc_type = tool_choice.get("type", "")
    # // [LAW:dataflow-not-control-flow] Type → value dispatch.
    mapping: dict[str, object] = {
        "auto": "auto",
        "any": "required",
        "none": "none",
    }
    result = mapping.get(tc_type)
    if result is not None:
        return result
    # Named tool
    if tc_type == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    return None


def copilot_chat_completions_url(base_url: str) -> str:
    """Build the Copilot Chat Completions API URL.

    // [LAW:one-source-of-truth] Chat Completions endpoint path lives here only.
    """
    return base_url.rstrip("/") + "/chat/completions"


def copilot_chat_headers(
    original_messages: list,
    token: str,
    content_length: int,
) -> dict[str, str]:
    """Build headers for Chat Completions upstream, including X-Initiator.

    // [LAW:single-enforcer] X-Initiator derivation happens at this boundary.
    """
    is_agent = any(
        isinstance(m, dict) and m.get("role") in ("assistant", "tool")
        for m in original_messages
    )
    headers = copilot_upstream_headers({}, token, content_length)
    headers["X-Initiator"] = "agent" if is_agent else "user"
    return headers


# ─── Chat Completions SSE Response Translation ─────────────────────────────
#
# OpenAI Chat Completions uses standard SSE: `data: {...}\n\n`
# with `data: [DONE]` as termination. Each chunk has `choices[0].delta`.


_CHAT_STOP_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "end_turn",
}


@dataclass
class ChatTranslationState:
    """Tracks state during Chat Completions → Anthropic SSE translation.

    // [LAW:one-source-of-truth] Chat translation state lives here.
    """
    message_id: str = field(default_factory=lambda: "msg_" + uuid.uuid4().hex[:12])
    message_start_sent: bool = False
    block_index: int = 0
    content_block_open: bool = False
    # tool_call index → (block_index, id, name)
    tool_calls: dict[int, dict] = field(default_factory=dict)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def chat_chunk_to_anthropic_events(
    chunk: dict,
    state: ChatTranslationState,
) -> list[dict]:
    """Translate one Chat Completions chunk to Anthropic SSE events.

    // [LAW:dataflow-not-control-flow] Each chunk phase produces events unconditionally.
    """
    events: list[dict] = []

    choices = chunk.get("choices", [])
    if not choices:
        return events

    choice = choices[0]
    delta = choice.get("delta", {})

    # First chunk → message_start
    if not state.message_start_sent:
        state.model = chunk.get("model", "copilot")
        usage = chunk.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        state.input_tokens = usage.get("prompt_tokens", 0) - cached
        events.append({
            "type": "message_start",
            "message": {
                "id": state.message_id,
                "type": "message",
                "role": "assistant",
                "model": state.model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": state.input_tokens,
                    "output_tokens": 0,
                    "cache_read_input_tokens": cached,
                    "cache_creation_input_tokens": 0,
                },
            },
        })
        state.message_start_sent = True

    # Text delta
    text_content = delta.get("content")
    if text_content is not None:
        events.extend(_chat_handle_text_delta(text_content, state))

    # Tool calls
    tool_calls = delta.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            events.extend(_chat_handle_tool_call_delta(tc, state))

    # Finish reason → close blocks + message_delta + message_stop
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None:
        events.extend(_chat_handle_finish(finish_reason, chunk, state))

    return events


def _chat_handle_text_delta(text: str, state: ChatTranslationState) -> list[dict]:
    """Handle text content delta — open text block if needed, emit delta."""
    events: list[dict] = []

    # Close any open tool block first
    if state.content_block_open and _is_tool_block(state):
        events.append({"type": "content_block_stop", "index": state.block_index})
        state.block_index += 1
        state.content_block_open = False

    # Open text block if not already open
    if not state.content_block_open:
        events.append({
            "type": "content_block_start",
            "index": state.block_index,
            "content_block": {"type": "text", "text": ""},
        })
        state.content_block_open = True

    events.append({
        "type": "content_block_delta",
        "index": state.block_index,
        "delta": {"type": "text_delta", "text": text},
    })
    return events


def _chat_handle_tool_call_delta(tc: dict, state: ChatTranslationState) -> list[dict]:
    """Handle a tool_calls[] delta entry."""
    events: list[dict] = []
    tc_index = tc.get("index", 0)

    # New tool call (has id + function.name)
    tc_id = tc.get("id")
    tc_func = tc.get("function") or {}
    tc_name = tc_func.get("name")

    if tc_id and tc_name:
        # Close any open block
        if state.content_block_open:
            events.append({"type": "content_block_stop", "index": state.block_index})
            state.block_index += 1
            state.content_block_open = False

        block_idx = state.block_index
        state.tool_calls[tc_index] = {
            "block_index": block_idx,
            "id": tc_id,
            "name": tc_name,
        }
        events.append({
            "type": "content_block_start",
            "index": block_idx,
            "content_block": {
                "type": "tool_use",
                "id": tc_id,
                "name": tc_name,
                "input": {},
            },
        })
        state.content_block_open = True

    # Arguments delta
    args_delta = tc_func.get("arguments")
    if args_delta:
        tc_info = state.tool_calls.get(tc_index)
        if tc_info is not None:
            events.append({
                "type": "content_block_delta",
                "index": tc_info["block_index"],
                "delta": {"type": "input_json_delta", "partial_json": args_delta},
            })

    return events


def _chat_handle_finish(
    finish_reason: str,
    chunk: dict,
    state: ChatTranslationState,
) -> list[dict]:
    """Handle finish_reason — close blocks, emit message_delta + message_stop."""
    events: list[dict] = []

    # Close any open block
    if state.content_block_open:
        events.append({"type": "content_block_stop", "index": state.block_index})
        state.content_block_open = False

    # Usage from final chunk
    usage = chunk.get("usage") or {}
    output_tokens = usage.get("completion_tokens", 0)
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    input_tokens = usage.get("prompt_tokens", 0) - cached

    stop_reason = _CHAT_STOP_REASON_MAP.get(finish_reason, "end_turn")

    events.append({
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cached,
        },
    })
    events.append({"type": "message_stop"})
    return events


def _is_tool_block(state: ChatTranslationState) -> bool:
    """Check if the current open block is a tool_use block."""
    return any(
        tc["block_index"] == state.block_index
        for tc in state.tool_calls.values()
    )
