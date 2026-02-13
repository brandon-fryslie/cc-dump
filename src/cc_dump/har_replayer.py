"""HAR replay module - loads HAR files and converts to synthetic event streams.

This is the inverse of har_recorder.py: complete messages -> synthetic SSE events.
The synthetic events match the format that formatting.py expects from the live pipeline.
"""

import json
import sys

from cc_dump.event_types import (
    ContentBlockStopEvent,
    InputJsonDeltaEvent,
    MessageDeltaEvent,
    MessageInfo,
    MessageRole,
    MessageStartEvent,
    MessageStopEvent,
    PipelineEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseDoneEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    StopReason,
    TextBlockStartEvent,
    TextDeltaEvent,
    ToolUseBlockStartEvent,
    Usage,
)


def load_har(path: str) -> list[tuple[dict, dict, int, dict, dict]]:
    """Load HAR file and extract request/response pairs.

    Args:
        path: Path to HAR file

    Returns:
        List of (request_headers, request_body, response_status, response_headers, complete_message) tuples

    Raises:
        ValueError: If HAR structure is invalid
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    with open(path, "r", encoding="utf-8") as f:
        har = json.load(f)

    # Validate HAR structure
    if "log" not in har:
        raise ValueError("Invalid HAR: missing 'log' key")

    log = har["log"]
    if "entries" not in log:
        raise ValueError("Invalid HAR: missing 'log.entries' key")

    entries = log["entries"]
    if not isinstance(entries, list):
        raise ValueError("Invalid HAR: log.entries must be a list")

    pairs = []
    for i, entry in enumerate(entries):
        try:
            # Extract request body
            if "request" not in entry:
                raise ValueError(f"Entry {i}: missing 'request' key")
            request = entry["request"]

            if "postData" not in request:
                raise ValueError(f"Entry {i}: missing 'request.postData' key")

            post_data = request["postData"]
            if "text" not in post_data:
                raise ValueError(f"Entry {i}: missing 'request.postData.text' key")

            request_body = json.loads(post_data["text"])

            # Extract response body
            if "response" not in entry:
                raise ValueError(f"Entry {i}: missing 'response' key")
            response = entry["response"]

            if "content" not in response:
                raise ValueError(f"Entry {i}: missing 'response.content' key")

            content = response["content"]
            if "text" not in content:
                raise ValueError(f"Entry {i}: missing 'response.content.text' key")

            complete_message = json.loads(content["text"])

            # Validate that response is a complete message (not SSE stream)
            if "type" not in complete_message or complete_message["type"] != "message":
                raise ValueError(
                    f"Entry {i}: response is not a complete message (expected type='message')"
                )

            # Extract request headers
            request_headers = {}
            if "headers" in request:
                for header in request["headers"]:
                    if (
                        isinstance(header, dict)
                        and "name" in header
                        and "value" in header
                    ):
                        request_headers[header["name"]] = header["value"]

            # Extract response status and headers
            response_status = response.get("status", 200)
            response_headers = {}
            if "headers" in response:
                for header in response["headers"]:
                    if (
                        isinstance(header, dict)
                        and "name" in header
                        and "value" in header
                    ):
                        response_headers[header["name"]] = header["value"]

            pairs.append(
                (
                    request_headers,
                    request_body,
                    response_status,
                    response_headers,
                    complete_message,
                )
            )

        except (KeyError, json.JSONDecodeError, ValueError) as e:
            sys.stderr.write(f"[har_replayer] Warning: skipping entry {i}: {e}\n")
            sys.stderr.flush()
            continue

    if not pairs:
        raise ValueError("HAR file contains no valid entries")

    return pairs


def convert_to_events(
    request_headers: dict,
    request_body: dict,
    response_status: int,
    response_headers: dict,
    complete_message: dict,
) -> list[PipelineEvent]:
    """Convert a complete request/response pair to typed pipeline events.

    This function "explodes" a complete message back into the SSE event sequence
    that the live pipeline produces.

    Args:
        request_headers: Request headers dict
        request_body: Request body dict
        response_status: HTTP status code
        response_headers: Response headers dict
        complete_message: Complete Claude message (non-streaming format)

    Returns:
        List of typed PipelineEvent objects
    """
    events: list[PipelineEvent] = []

    # Request events
    events.append(RequestHeadersEvent(headers=request_headers))
    events.append(RequestBodyEvent(body=request_body))

    # Response start
    events.append(ResponseHeadersEvent(status_code=response_status, headers=response_headers))

    # Reconstruct SSE event sequence from complete message
    # 1. message_start
    raw_usage = complete_message.get("usage", {})
    if not isinstance(raw_usage, dict):
        raw_usage = {}
    start_usage = Usage(
        input_tokens=raw_usage.get("input_tokens", 0),
        output_tokens=0,  # Output tokens are 0 in message_start
        cache_read_input_tokens=raw_usage.get("cache_read_input_tokens", 0),
        cache_creation_input_tokens=raw_usage.get("cache_creation_input_tokens", 0),
    )
    role_str = complete_message.get("role", "assistant")
    role = MessageRole(role_str) if role_str in ("user", "assistant") else MessageRole.ASSISTANT
    message_info = MessageInfo(
        id=complete_message.get("id", ""),
        role=role,
        model=complete_message.get("model", ""),
        usage=start_usage,
    )
    events.append(ResponseSSEEvent(sse_event=MessageStartEvent(message=message_info)))

    # 2. Content blocks
    content_blocks = complete_message.get("content", [])
    block_index = 0
    for block in content_blocks:
        block_type = block.get("type", "")

        if block_type == "text":
            # Text block: start -> delta -> stop
            events.append(ResponseSSEEvent(
                sse_event=TextBlockStartEvent(index=block_index)
            ))

            # Emit text as a single delta (not character-by-character)
            text = block.get("text", "")
            if text:
                events.append(ResponseSSEEvent(
                    sse_event=TextDeltaEvent(index=block_index, text=text)
                ))

            # Block stop
            events.append(ResponseSSEEvent(
                sse_event=ContentBlockStopEvent(index=block_index)
            ))
            block_index += 1

        elif block_type == "tool_use":
            # Tool use block: start -> input_json_deltas -> stop
            tool_use_id = block.get("id", "")
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})

            events.append(ResponseSSEEvent(
                sse_event=ToolUseBlockStartEvent(
                    index=block_index, id=tool_use_id, name=tool_name
                )
            ))

            # Emit tool input as a single JSON delta
            input_json = json.dumps(tool_input)
            if input_json:
                events.append(ResponseSSEEvent(
                    sse_event=InputJsonDeltaEvent(
                        index=block_index, partial_json=input_json
                    )
                ))

            # Block stop
            events.append(ResponseSSEEvent(
                sse_event=ContentBlockStopEvent(index=block_index)
            ))
            block_index += 1

        else:
            # Unknown block type - log warning but continue
            sys.stderr.write(
                f"[har_replayer] Warning: unknown content block type '{block_type}'\n"
            )
            sys.stderr.flush()

    # 3. message_delta (stop_reason and usage)
    stop_reason_str = complete_message.get("stop_reason") or ""
    try:
        stop_reason = StopReason(stop_reason_str)
    except ValueError:
        stop_reason = StopReason.NONE
    stop_sequence = complete_message.get("stop_sequence") or ""
    output_tokens = raw_usage.get("output_tokens", 0)

    events.append(ResponseSSEEvent(
        sse_event=MessageDeltaEvent(
            stop_reason=stop_reason,
            stop_sequence=stop_sequence,
            output_tokens=output_tokens,
        )
    ))

    # 4. message_stop
    events.append(ResponseSSEEvent(sse_event=MessageStopEvent()))

    # 5. response_done
    events.append(ResponseDoneEvent())

    return events
