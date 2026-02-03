"""HAR replay module - loads HAR files and converts to synthetic event streams.

This is the inverse of har_recorder.py: complete messages → synthetic SSE events.
The synthetic events match the format that formatting.py expects from the live pipeline.
"""

import json
import sys


def load_har(path: str) -> list[tuple[dict, dict]]:
    """Load HAR file and extract request/response pairs.

    Args:
        path: Path to HAR file

    Returns:
        List of (request_body, complete_message) tuples

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
                    if isinstance(header, dict) and "name" in header and "value" in header:
                        request_headers[header["name"]] = header["value"]

            # Extract response status and headers
            response_status = response.get("status", 200)
            response_headers = {}
            if "headers" in response:
                for header in response["headers"]:
                    if isinstance(header, dict) and "name" in header and "value" in header:
                        response_headers[header["name"]] = header["value"]

            pairs.append((request_headers, request_body, response_status, response_headers, complete_message))

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
) -> list[tuple]:
    """Convert a complete request/response pair to synthetic event tuples.

    This function "explodes" a complete message back into the SSE event sequence
    that the live pipeline produces. The events match exactly what formatting.py
    expects from proxy.py.

    Args:
        request_headers: Request headers dict
        request_body: Request body dict
        response_status: HTTP status code
        response_headers: Response headers dict
        complete_message: Complete Claude message (non-streaming format)

    Returns:
        List of event tuples in the format:
        - ("request_headers", headers_dict)
        - ("request", request_body_dict)
        - ("response_headers", status_code, headers_dict)
        - ("response_event", event_type, event_data)
        - ("response_done",)
    """
    events = []

    # Request events
    events.append(("request_headers", request_headers))
    events.append(("request", request_body))

    # Response start
    events.append(("response_headers", response_status, response_headers))

    # Reconstruct SSE event sequence from complete message
    # 1. message_start
    message_start_event = {
        "type": "message_start",
        "message": {
            "id": complete_message.get("id", ""),
            "type": "message",
            "role": complete_message.get("role", "assistant"),
            "model": complete_message.get("model", ""),
            "usage": dict(complete_message.get("usage", {})),
        },
    }
    # Set output_tokens to 0 in message_start (it's updated in message_delta)
    if "output_tokens" in message_start_event["message"]["usage"]:
        message_start_event["message"]["usage"]["output_tokens"] = 0

    events.append(("response_event", "message_start", message_start_event))

    # 2. Content blocks
    content_blocks = complete_message.get("content", [])
    for block in content_blocks:
        block_type = block.get("type", "")

        if block_type == "text":
            # Text block: start → delta → stop
            content_block_start = {
                "type": "content_block_start",
                "index": len([e for e in events if e[0] == "response_event" and e[1] == "content_block_start"]),
                "content_block": {"type": "text", "text": ""},
            }
            events.append(("response_event", "content_block_start", content_block_start))

            # Emit text as a single delta (not character-by-character)
            text = block.get("text", "")
            if text:
                content_block_delta = {
                    "type": "content_block_delta",
                    "index": len([e for e in events if e[0] == "response_event" and e[1] == "content_block_start"]) - 1,
                    "delta": {"type": "text_delta", "text": text},
                }
                events.append(("response_event", "content_block_delta", content_block_delta))

            # Block stop
            content_block_stop = {
                "type": "content_block_stop",
                "index": len([e for e in events if e[0] == "response_event" and e[1] == "content_block_start"]) - 1,
            }
            events.append(("response_event", "content_block_stop", content_block_stop))

        elif block_type == "tool_use":
            # Tool use block: start → input_json_deltas → stop
            tool_use_id = block.get("id", "")
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})

            content_block_start = {
                "type": "content_block_start",
                "index": len([e for e in events if e[0] == "response_event" and e[1] == "content_block_start"]),
                "content_block": {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                },
            }
            events.append(("response_event", "content_block_start", content_block_start))

            # Emit tool input as a single JSON delta (not character-by-character)
            input_json = json.dumps(tool_input)
            if input_json:
                content_block_delta = {
                    "type": "content_block_delta",
                    "index": len([e for e in events if e[0] == "response_event" and e[1] == "content_block_start"]) - 1,
                    "delta": {"type": "input_json_delta", "partial_json": input_json},
                }
                events.append(("response_event", "content_block_delta", content_block_delta))

            # Block stop
            content_block_stop = {
                "type": "content_block_stop",
                "index": len([e for e in events if e[0] == "response_event" and e[1] == "content_block_start"]) - 1,
            }
            events.append(("response_event", "content_block_stop", content_block_stop))

        else:
            # Unknown block type - log warning but continue
            sys.stderr.write(f"[har_replayer] Warning: unknown content block type '{block_type}'\n")
            sys.stderr.flush()

    # 3. message_delta (stop_reason and usage)
    message_delta_event = {
        "type": "message_delta",
        "delta": {},
        "usage": {},
    }

    stop_reason = complete_message.get("stop_reason")
    if stop_reason:
        message_delta_event["delta"]["stop_reason"] = stop_reason

    stop_sequence = complete_message.get("stop_sequence")
    if stop_sequence:
        message_delta_event["delta"]["stop_sequence"] = stop_sequence

    # Output tokens in message_delta
    usage = complete_message.get("usage", {})
    if "output_tokens" in usage:
        message_delta_event["usage"]["output_tokens"] = usage["output_tokens"]

    events.append(("response_event", "message_delta", message_delta_event))

    # 4. message_stop
    message_stop_event = {"type": "message_stop"}
    events.append(("response_event", "message_stop", message_stop_event))

    # 5. response_done
    events.append(("response_done",))

    return events
