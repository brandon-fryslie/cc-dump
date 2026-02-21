"""HAR replay module - loads HAR files and converts to pipeline events.

Converts complete request/response pairs from HAR files into the same
typed events the live pipeline produces.
"""

import json
import sys
import time
import uuid

from cc_dump.event_types import (
    PipelineEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseNonStreamingEvent,
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

    Args:
        request_headers: Request headers dict
        request_body: Request body dict
        response_status: HTTP status code
        response_headers: Response headers dict
        complete_message: Complete Claude message (non-streaming format)

    Returns:
        List of typed PipelineEvent objects
    """
    request_id = uuid.uuid4().hex
    return [
        RequestHeadersEvent(headers=request_headers),
        RequestBodyEvent(body=request_body),
        ResponseNonStreamingEvent(
            status_code=response_status,
            headers=response_headers,
            body=complete_message,
            request_id=request_id,
            seq=0,
            recv_ns=time.monotonic_ns(),
        ),
    ]
