"""Event schema translation from generic proxy events to handler-expected format.

Reloadable module. Pure functions, no state.

SINGLE ENFORCER for event format translation (one-way deps, single-enforcer).
"""

import json


def adapt_proxy_event(event: tuple) -> list[tuple]:
    """Translate generic proxy events to handler-expected format.

    Single enforcer for event schema translation. Converts low-level proxy
    events (raw HTTP) to high-level handler events (parsed, structured).

    Translation table:
    - ("request", method, url, headers, body_bytes) →
        [("request_headers", headers), ("request", parsed_json)]
        If JSON parse fails, wraps as {"_raw": True, "_method": method, ...}

    - ("response_start", status, headers) →
        [("response_headers", status, headers)]

    - ("sse_event", type_str, data_str) →
        [("response_event", type_str, parsed_json)]
        If parse fails, wraps as {"_raw_data": data_str}

    - ("response_body", bytes, content_type) →
        [] (dropped, no downstream handler)

    - ("response_done", duration_ms) →
        [("response_done",)]

    - error/proxy_error/log →
        pass-through unchanged

    Args:
        event: Tuple from proxy.py event queue

    Returns:
        List of events for downstream handlers. May be empty, single, or multiple.
    """
    event_type = event[0]

    # Request event: split into headers + body
    if event_type == "request":
        _, method, url, headers, body_bytes = event

        # Always emit request_headers first
        result = [("request_headers", headers)]

        # Try parsing body as JSON
        if body_bytes:
            try:
                body_dict = json.loads(body_bytes)
                result.append(("request", body_dict))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Wrap raw data for downstream handlers
                result.append(("request", {
                    "_raw": True,
                    "_method": method,
                    "_url": url,
                    "_body_bytes": body_bytes.decode("utf-8", errors="replace"),
                }))
        else:
            # No body (GET/HEAD/DELETE)
            result.append(("request", {
                "_raw": True,
                "_method": method,
                "_url": url,
            }))

        return result

    # Response start: pass through with renamed event type
    elif event_type == "response_start":
        _, status, headers = event
        return [("response_headers", status, headers)]

    # SSE event: parse data as JSON
    elif event_type == "sse_event":
        _, type_str, data_str = event
        try:
            data_dict = json.loads(data_str)
            return [("response_event", type_str, data_dict)]
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Wrap raw data for downstream handlers
            return [("response_event", type_str, {"_raw_data": data_str})]

    # Response body: drop (no downstream handler)
    elif event_type == "response_body":
        return []

    # Response done: simplify signature
    elif event_type == "response_done":
        return [("response_done",)]

    # Pass-through events (error, proxy_error, log)
    else:
        return [event]
