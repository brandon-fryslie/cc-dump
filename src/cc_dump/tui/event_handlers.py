"""Event handling logic - pure functions for processing proxy events.

This module is RELOADABLE. It contains all the logic for what to do when
events arrive from the proxy. The app.py module calls into these functions
but the actual behavior can be hot-swapped.
"""

import cc_dump.analysis
import cc_dump.formatting


def handle_request(event, state, widgets, app_state):
    """Handle a request event.

    Args:
        event: The event tuple ("request", body)
        state: The content tracking state dict
        widgets: Dict with widget references (conv, stats, timeline, economics)
        app_state: Dict with app-level state (turn_budgets, current_budget, all_invocations)

    Returns:
        Updated app_state dict
    """
    body = event[1]
    blocks = cc_dump.formatting.format_request(body, state)

    conv = widgets["conv"]
    stats = widgets["stats"]
    filters = widgets["filters"]

    for block in blocks:
        conv.append_block(block, filters)
        # Capture the budget for this turn
        if isinstance(block, cc_dump.formatting.TurnBudgetBlock):
            app_state["current_budget"] = block.budget

    conv.finish_turn()

    # Correlate tool invocations from this request
    messages = body.get("messages", [])
    invocations = cc_dump.analysis.correlate_tools(messages)
    app_state["all_invocations"].extend(invocations)

    # Update stats
    stats.update_stats(requests=state["request_counter"])

    return app_state


def handle_response_event(event, state, widgets, app_state):
    """Handle a response_event.

    Args:
        event: The event tuple ("response_event", event_type, data)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state

    Returns:
        Updated app_state dict
    """
    event_type, data = event[1], event[2]
    blocks = cc_dump.formatting.format_response_event(event_type, data)

    conv = widgets["conv"]
    stats = widgets["stats"]
    filters = widgets["filters"]

    for block in blocks:
        conv.append_block(block, filters)

        # Extract stats from message_start and message_delta
        if isinstance(block, cc_dump.formatting.StreamInfoBlock):
            stats.update_stats(model=block.model)
            # StreamInfoBlock is created from message_start event
            # Extract usage data here since message_start creates StreamInfoBlock
            if event_type == "message_start":
                msg = data.get("message", {})
                usage = msg.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                cache_create = usage.get("cache_creation_input_tokens", 0)

                stats.update_stats(
                    input_tokens=input_tokens,
                    cache_read_tokens=cache_read,
                    cache_creation_tokens=cache_create,
                )
                # Fill actual data into current budget
                current_budget = app_state.get("current_budget")
                if current_budget:
                    current_budget.actual_input_tokens = input_tokens
                    current_budget.actual_cache_read_tokens = cache_read
                    current_budget.actual_cache_creation_tokens = cache_create

        elif event_type == "message_delta":
            usage = data.get("usage", {})
            stats.update_stats(
                output_tokens=usage.get("output_tokens", 0),
            )

    return app_state


def handle_response_done(event, state, widgets, app_state, refresh_callbacks):
    """Handle response_done event.

    Args:
        event: The event tuple ("response_done",)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state
        refresh_callbacks: Dict with refresh functions (economics, timeline)

    Returns:
        Updated app_state dict
    """
    conv = widgets["conv"]
    filters = widgets["filters"]
    show_expand = widgets.get("show_expand", False)

    conv.finish_turn()

    # Finalize turn budget and update panels
    current_budget = app_state.get("current_budget")
    if current_budget:
        app_state["turn_budgets"].append(current_budget)
        # Re-render expand view to show cache data
        if show_expand:
            conv.rerender(filters)
        app_state["current_budget"] = None

    # Update economics and timeline panels
    if "refresh_economics" in refresh_callbacks:
        refresh_callbacks["refresh_economics"]()
    if "refresh_timeline" in refresh_callbacks:
        refresh_callbacks["refresh_timeline"]()

    return app_state


def handle_error(event, state, widgets, app_state):
    """Handle an error event.

    Args:
        event: The event tuple ("error", code, reason)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state

    Returns:
        Updated app_state dict
    """
    code, reason = event[1], event[2]
    block = cc_dump.formatting.ErrorBlock(code=code, reason=reason)

    conv = widgets["conv"]
    filters = widgets["filters"]

    conv.append_block(block, filters)
    conv.finish_turn()

    return app_state


def handle_proxy_error(event, state, widgets, app_state):
    """Handle a proxy_error event.

    Args:
        event: The event tuple ("proxy_error", error_str)
        state: The content tracking state dict
        widgets: Dict with widget references
        app_state: Dict with app-level state

    Returns:
        Updated app_state dict
    """
    err = event[1]
    block = cc_dump.formatting.ProxyErrorBlock(error=err)

    conv = widgets["conv"]
    filters = widgets["filters"]

    conv.append_block(block, filters)
    conv.finish_turn()

    return app_state
