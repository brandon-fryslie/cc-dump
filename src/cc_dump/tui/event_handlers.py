"""Event handling logic - pure functions for processing proxy events.

This module is RELOADABLE. It contains all the logic for what to do when
events arrive from the proxy. The app.py module calls into these functions
but the actual behavior can be hot-swapped.
"""

import cc_dump.analysis
import cc_dump.formatting
from cc_dump.formatting import NewSessionBlock


def handle_request_headers(event, state, widgets, app_state, log_fn):
    """Handle request_headers event.

    Stores request headers in app_state to be included with the request turn.

    Args:
        event: The event tuple ("request_headers", headers_dict)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    headers_dict = event[1]
    # Store headers temporarily - will be consumed by handle_request
    app_state["pending_request_headers"] = headers_dict
    log_fn("DEBUG", f"Stored request headers: {len(headers_dict)} headers")
    return app_state


def handle_request(event, state, widgets, app_state, log_fn):
    """Handle a request event.

    Args:
        event: The event tuple ("request", body)
        state: The content tracking state dict
        widgets: Dict with widget references (conv, stats, timeline, economics)
        app_state: Dict with app-level state (current_turn_usage)
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    body = event[1]

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


def handle_response_headers(event, state, widgets, app_state, log_fn):
    """Handle response_headers event.

    Formats and displays HTTP response headers at the start of streaming response.

    Args:
        event: The event tuple ("response_headers", status_code, headers_dict)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    status_code = event[1]
    headers_dict = event[2]

    try:
        blocks = cc_dump.formatting.format_response_headers(status_code, headers_dict)
        if blocks:
            conv = widgets["conv"]
            filters = widgets["filters"]

            # Begin streaming turn if not started
            conv.begin_streaming_turn()

            # Append response header blocks
            for block in blocks:
                conv.append_streaming_block(block, filters)

            log_fn(
                "DEBUG",
                f"Displayed response headers: HTTP {status_code}, {len(headers_dict)} headers",
            )
    except Exception as e:
        log_fn("ERROR", f"Error handling response headers: {e}")
        raise

    return app_state


def handle_response_event(event, state, widgets, app_state, log_fn):
    """Handle a response_event.

    Args:
        event: The event tuple ("response_event", event_type, data)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    event_type, data = event[1], event[2]

    try:
        blocks = cc_dump.formatting.format_response_event(event_type, data)

        conv = widgets["conv"]
        stats = widgets["stats"]
        filters = widgets["filters"]

        # Begin streaming turn if not started
        if blocks:
            conv.begin_streaming_turn()

        for block in blocks:
            # Append to ConversationView streaming turn
            conv.append_streaming_block(block, filters)

            # Extract stats from message_start and message_delta
            if isinstance(block, cc_dump.formatting.StreamInfoBlock):
                stats.update_stats(model=block.model)
                # Extract usage data from message_start for current turn tracking
                if event_type == "message_start":
                    msg = data.get("message", {})
                    usage = msg.get("usage", {})
                    # Track current turn usage for real-time display
                    current_turn = app_state.get("current_turn_usage", {})
                    current_turn["input_tokens"] = usage.get("input_tokens", 0)
                    current_turn["cache_read_tokens"] = usage.get(
                        "cache_read_input_tokens", 0
                    )
                    current_turn["cache_creation_tokens"] = usage.get(
                        "cache_creation_input_tokens", 0
                    )
                    app_state["current_turn_usage"] = current_turn

            elif event_type == "message_delta":
                usage = data.get("usage", {})
                # Track output tokens for current turn
                current_turn = app_state.get("current_turn_usage", {})
                current_turn["output_tokens"] = usage.get("output_tokens", 0)
                app_state["current_turn_usage"] = current_turn
    except Exception as e:
        log_fn("ERROR", f"Error handling response event: {e}")
        raise

    return app_state


def handle_response_done(event, state, widgets, app_state, log_fn):
    """Handle response_done event.

    Args:
        event: The event tuple ("response_done",)
        state: The content tracking state dict
        widgets: Dict with widget references (includes refresh_callbacks and analytics_store)
        app_state: Dict with app-level state
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
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


def handle_error(event, state, widgets, app_state, log_fn):
    """Handle an error event.

    Args:
        event: The event tuple ("error", code, reason)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    code, reason = event[1], event[2]

    log_fn("ERROR", f"HTTP Error {code}: {reason}")

    block = cc_dump.formatting.ErrorBlock(code=code, reason=reason)

    conv = widgets["conv"]

    # Single block, non-streaming: add directly
    conv.add_turn([block])

    return app_state


def handle_proxy_error(event, state, widgets, app_state, log_fn):
    """Handle a proxy_error event.

    Args:
        event: The event tuple ("proxy_error", error_str)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    err = event[1]

    log_fn("ERROR", f"Proxy error: {err}")

    block = cc_dump.formatting.ProxyErrorBlock(error=err)

    conv = widgets["conv"]

    # Single block, non-streaming: add directly
    conv.add_turn([block])

    return app_state


def handle_log(event, state, widgets, app_state, log_fn):
    """Handle a log event.

    Args:
        event: The event tuple ("log", method, path, status)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    _, method, path, status = event
    log_fn("DEBUG", f"HTTP {method} {path} -> {status}")
    return app_state


def _noop(event, state, widgets, app_state, log_fn):
    """No-op handler for events that need no action."""
    return app_state


# [LAW:dataflow-not-control-flow] Event dispatch table
EVENT_HANDLERS = {
    "request_headers": handle_request_headers,
    "request": handle_request,
    "response_headers": handle_response_headers,
    "response_start": _noop,
    "response_event": handle_response_event,
    "response_done": handle_response_done,
    "error": handle_error,
    "proxy_error": handle_proxy_error,
    "log": handle_log,
}
