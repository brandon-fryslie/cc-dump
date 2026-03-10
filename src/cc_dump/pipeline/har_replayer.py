"""HAR replay module - loads HAR files and converts to pipeline events.

Converts complete request/response pairs from HAR files into the same
typed events the live pipeline produces.
"""

import json
import logging

import cc_dump.providers
from cc_dump.pipeline.event_types import (
    PipelineEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseHeadersEvent,
    ResponseCompleteEvent,
    event_envelope,
    new_request_id,
)

logger = logging.getLogger(__name__)


def _load_json_object(text: str, *, entry_index: int, field_name: str) -> dict[str, object]:
    """Decode a JSON object payload or raise a boundary-localized ValueError.

    // [LAW:single-enforcer] HAR replay owns JSON-object validation at the file boundary.
    """
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"Entry {entry_index}: {field_name} must decode to a JSON object")
    return payload

def load_har(path: str) -> list[tuple[dict, dict, int, dict, dict, str]]:
    """Load HAR file and extract request/response pairs.

    Args:
        path: Path to HAR file

    Returns:
        List of (request_headers, request_body, response_status, response_headers, complete_message, provider) tuples

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

            request_body = _load_json_object(
                post_data["text"],
                entry_index=i,
                field_name="request.postData.text",
            )

            # Extract response body
            if "response" not in entry:
                raise ValueError(f"Entry {i}: missing 'response' key")
            response = entry["response"]

            if "content" not in response:
                raise ValueError(f"Entry {i}: missing 'response.content' key")

            content = response["content"]
            if "text" not in content:
                raise ValueError(f"Entry {i}: missing 'response.content.text' key")

            complete_message = _load_json_object(
                content["text"],
                entry_index=i,
                field_name="response.content.text",
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

            # // [LAW:one-source-of-truth] HAR provider inference precedence is centralized.
            provider = cc_dump.providers.infer_provider_from_har_entry(
                entry,
                complete_message=complete_message,
            )

            if not cc_dump.providers.is_complete_response_for_provider(provider, complete_message):
                raise ValueError(
                    f"Entry {i}: response is not a recognized complete message "
                    f"for provider={provider!r}"
                )

            pairs.append(
                (
                    request_headers,
                    request_body,
                    response_status,
                    response_headers,
                    complete_message,
                    provider,
                )
            )

        except (KeyError, json.JSONDecodeError, ValueError) as e:
            logger.warning("skipping HAR entry %s: %s", i, e)
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
    provider: str = "anthropic",
) -> list[PipelineEvent]:
    """Convert a complete request/response pair to typed pipeline events.

    Args:
        request_headers: Request headers dict
        request_body: Request body dict
        response_status: HTTP status code
        response_headers: Response headers dict
        complete_message: Complete message dict (Anthropic or OpenAI format)
        provider: API provider identifier

    Returns:
        List of typed PipelineEvent objects
    """
    request_id = new_request_id()
    return [
        # // [LAW:one-source-of-truth] Replay uses same request envelope shape as live proxy.
        RequestHeadersEvent(
            headers=request_headers,
            **event_envelope(
                request_id=request_id,
                seq=0,
                provider=provider,
            ),
        ),
        RequestBodyEvent(
            body=request_body,
            **event_envelope(
                request_id=request_id,
                seq=1,
                provider=provider,
            ),
        ),
        ResponseHeadersEvent(
            status_code=response_status,
            headers=response_headers,
            **event_envelope(
                request_id=request_id,
                seq=2,
                provider=provider,
            ),
        ),
        ResponseCompleteEvent(
            body=complete_message,
            **event_envelope(
                request_id=request_id,
                seq=3,
                provider=provider,
            ),
        ),
    ]
