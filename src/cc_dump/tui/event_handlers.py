"""Event handling logic - pure functions for processing proxy events.

This module is RELOADABLE. It contains all the logic for what to do when
events arrive from the proxy. The app.py module calls into these functions
but the actual behavior can be hot-swapped.
"""

import cc_dump.analysis
import cc_dump.formatting


def handle_request(event, state, widgets, app_state, log_fn):
    """Handle a request event.

    Args:
        event: The event tuple ("request", body)
        state: The content tracking state dict
        widgets: Dict with widget references (conv, streaming, stats, timeline, economics)
        app_state: Dict with app-level state (current_turn_usage)
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    body = event[1]

    try:
        blocks = cc_dump.formatting.format_request(body, state)

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

        streaming = widgets["streaming"]
        stats = widgets["stats"]
        filters = widgets["filters"]

        for block in blocks:
            # Stream to StreamingRichLog for immediate display
            streaming.append_block(block, filters)

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
                    current_turn["cache_read_tokens"] = usage.get("cache_read_input_tokens", 0)
                    current_turn["cache_creation_tokens"] = usage.get("cache_creation_input_tokens", 0)
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


def handle_response_done(event, state, widgets, app_state, refresh_callbacks, db_context, log_fn):
    """Handle response_done event.

    Args:
        event: The event tuple ("response_done",)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state
        refresh_callbacks: Dict with refresh functions (economics, timeline)
        db_context: Dict with db_path and session_id for database access
        log_fn: Function to log application messages

    Returns:
        Updated app_state dict
    """
    try:
        streaming = widgets["streaming"]
        conv = widgets["conv"]
        stats = widgets["stats"]
        filters = widgets["filters"]
        show_expand = widgets.get("show_expand", False)

        # Finalize streaming: get blocks and add as turn to ConversationView
        blocks = streaming.finalize()
        if blocks:
            conv.add_turn(blocks)

        # Clear current turn usage (turn is now committed to DB)
        app_state["current_turn_usage"] = {}

        # Refresh stats panel from database (merges current turn if streaming)
        db_path = db_context.get("db_path")
        session_id = db_context.get("session_id")
        if db_path and session_id:
            stats.refresh_from_db(db_path, session_id, current_turn=None)

        # Re-render expand view to show cache data
        if show_expand:
            conv.rerender(filters)

        # Update economics and timeline panels (these query database)
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
