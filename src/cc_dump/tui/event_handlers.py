"""Event handling logic - pure functions for processing proxy events.

This module is RELOADABLE. It contains all the logic for what to do when
events arrive from the proxy. The app.py module calls into these functions
but the actual behavior can be hot-swapped.
"""

import cc_dump.analysis
import cc_dump.formatting
from cc_dump.formatting import NewSessionBlock
from cc_dump.event_types import (
    PipelineEventKind,
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    ResponseDoneEvent,
    ErrorEvent,
    ProxyErrorEvent,
    LogEvent,
    MessageStartEvent,
    MessageDeltaEvent,
)


def handle_request_headers(event: RequestHeadersEvent, state, widgets, app_state, log_fn):
    """Handle request_headers event.

    Stores request headers in app_state to be included with the request turn.
    """
    headers_dict = event.headers
    # Store headers temporarily - will be consumed by handle_request
    app_state["pending_request_headers"] = headers_dict
    log_fn("DEBUG", f"Stored request headers: {len(headers_dict)} headers")
    return app_state


def handle_request(event: RequestBodyEvent, state, widgets, app_state, log_fn):
    """Handle a request event."""
    body = event.body

    try:
        # [LAW:one-source-of-truth] Header injection moved into format_request
        pending_headers = app_state.pop("pending_request_headers", None)
        blocks = cc_dump.formatting.format_request(body, state, request_headers=pending_headers)

        # Check for new session — signal to app for notification/message
        for block in blocks:
            if isinstance(block, NewSessionBlock):
                app_state["new_session_id"] = block.session_id
                break

        conv = widgets["conv"]
        stats = widgets["stats"]

        # Non-streaming: add turn directly to ConversationView
        conv.add_turn(blocks)

        # Update stats (only request count and model tracking - not tokens)
        stats.update_stats(requests=state["request_counter"])

        log_fn("DEBUG", f"Request #{state['request_counter']} processed")
    except Exception as e:
        log_fn("ERROR", f"Error handling request: {e}")
        raise

    return app_state


def handle_response_headers(event: ResponseHeadersEvent, state, widgets, app_state, log_fn):
    """Handle response_headers event."""
    status_code = event.status_code
    headers_dict = event.headers

    try:
        blocks = cc_dump.formatting.format_response_headers(status_code, headers_dict)
        conv = widgets["conv"]
        filters = widgets["filters"]

        # [LAW:dataflow-not-control-flow] Always begin turn (idempotent), process blocks
        conv.begin_streaming_turn()

        # Append response header blocks (empty list is safe)
        for block in blocks:
            conv.append_streaming_block(block, filters)

        if blocks:  # Only log if blocks were actually produced
            log_fn(
                "DEBUG",
                f"Displayed response headers: HTTP {status_code}, {len(headers_dict)} headers",
            )
    except Exception as e:
        log_fn("ERROR", f"Error handling response headers: {e}")
        raise

    return app_state


def handle_response_event(event: ResponseSSEEvent, state, widgets, app_state, log_fn):
    """Handle a response SSE event."""
    sse_event = event.sse_event

    try:
        blocks = cc_dump.formatting.format_response_event(sse_event)

        conv = widgets["conv"]
        stats = widgets["stats"]
        filters = widgets["filters"]

        # [LAW:dataflow-not-control-flow] Always begin turn (idempotent), process blocks
        conv.begin_streaming_turn()

        for block in blocks:
            # Append to ConversationView streaming turn
            conv.append_streaming_block(block, filters)

            # Extract stats from message_start and message_delta
            if isinstance(block, cc_dump.formatting.StreamInfoBlock):
                stats.update_stats(model=block.model)
                # Extract usage data from message_start for current turn tracking
                if isinstance(sse_event, MessageStartEvent):
                    usage = sse_event.message.usage
                    current_turn = app_state.get("current_turn_usage", {})
                    current_turn["input_tokens"] = usage.input_tokens
                    current_turn["cache_read_tokens"] = usage.cache_read_input_tokens
                    current_turn["cache_creation_tokens"] = usage.cache_creation_input_tokens
                    app_state["current_turn_usage"] = current_turn

            elif isinstance(sse_event, MessageDeltaEvent):
                # Track output tokens for current turn
                current_turn = app_state.get("current_turn_usage", {})
                current_turn["output_tokens"] = sse_event.output_tokens
                app_state["current_turn_usage"] = current_turn
    except Exception as e:
        log_fn("ERROR", f"Error handling response event: {e}")
        raise

    return app_state


def handle_response_done(event: ResponseDoneEvent, state, widgets, app_state, log_fn):
    """Handle response_done event."""
    try:
        conv = widgets["conv"]
        stats = widgets["stats"]
        filters = widgets["filters"]
        refresh_callbacks = widgets.get("refresh_callbacks", {})
        analytics_store = widgets.get("analytics_store")

        # Finalize streaming turn in ConversationView
        _ = conv.finalize_streaming_turn()

        # Clear current turn usage (turn is now committed to store)
        app_state["current_turn_usage"] = {}

        # Refresh stats panel from analytics store (merges current turn if streaming)
        if analytics_store is not None:
            stats.refresh_from_store(analytics_store, current_turn=None)

        # Re-render to show cache data in budget blocks
        budget_vis = filters.get("budget", cc_dump.formatting.HIDDEN)
        if budget_vis.visible:
            conv.rerender(filters)

        # Update economics and timeline panels (these query analytics store)
        if "refresh_economics" in refresh_callbacks:
            refresh_callbacks["refresh_economics"]()
        if "refresh_timeline" in refresh_callbacks:
            refresh_callbacks["refresh_timeline"]()

        log_fn("DEBUG", "Response completed")
    except Exception as e:
        log_fn("ERROR", f"Error handling response done: {e}")
        raise

    return app_state


def handle_error(event: ErrorEvent, state, widgets, app_state, log_fn):
    """Handle an error event."""
    code, reason = event.code, event.reason

    log_fn("ERROR", f"HTTP Error {code}: {reason}")

    block = cc_dump.formatting.ErrorBlock(code=code, reason=reason)

    conv = widgets["conv"]

    # Single block, non-streaming: add directly
    conv.add_turn([block])

    return app_state


def handle_proxy_error(event: ProxyErrorEvent, state, widgets, app_state, log_fn):
    """Handle a proxy_error event."""
    err = event.error

    log_fn("ERROR", f"Proxy error: {err}")

    block = cc_dump.formatting.ProxyErrorBlock(error=err)

    conv = widgets["conv"]

    # Single block, non-streaming: add directly
    conv.add_turn([block])

    return app_state


def handle_log(event: LogEvent, state, widgets, app_state, log_fn):
    """Handle a log event."""
    log_fn("DEBUG", f"HTTP {event.method} {event.path} -> {event.status}")
    return app_state


def _noop(event, state, widgets, app_state, log_fn):
    """No-op handler for events that need no action."""
    return app_state


# [LAW:dataflow-not-control-flow] Event dispatch table keyed by PipelineEventKind
EVENT_HANDLERS = {
    PipelineEventKind.REQUEST_HEADERS: handle_request_headers,
    PipelineEventKind.REQUEST: handle_request,
    PipelineEventKind.RESPONSE_HEADERS: handle_response_headers,
    PipelineEventKind.RESPONSE_EVENT: handle_response_event,
    PipelineEventKind.RESPONSE_DONE: handle_response_done,
    PipelineEventKind.ERROR: handle_error,
    PipelineEventKind.PROXY_ERROR: handle_proxy_error,
    PipelineEventKind.LOG: handle_log,
}
