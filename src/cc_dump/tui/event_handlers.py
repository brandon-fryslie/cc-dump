"""Event handling logic - pure functions for processing proxy events.

This module is RELOADABLE. It contains all the logic for what to do when
events arrive from the proxy. The app.py module calls into these functions
but the actual behavior can be hot-swapped.
"""

from collections.abc import Callable

import cc_dump.analysis
import cc_dump.formatting
import cc_dump.tui.stream_registry
from cc_dump.event_types import (
    PipelineEventKind,
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    ResponseNonStreamingEvent,
    ResponseCompleteEvent,
    ResponseDoneEvent,
    ErrorEvent,
    ProxyErrorEvent,
    LogEvent,
    MessageStartEvent,
    MessageDeltaEvent,
    ToolUseBlockStartEvent,
)

EventHandler = Callable[
    [object, dict[str, object], dict[str, object], dict[str, object], Callable[[str, str], None]],
    dict[str, object],
]


def _get_stream_registry(app_state):
    """Get or create the stream registry in app_state."""
    reg = app_state.get("stream_registry")
    if reg is None:
        reg = cc_dump.tui.stream_registry.StreamRegistry()
        app_state["stream_registry"] = reg
    return reg


def _stamp_block_tree(block, ctx) -> None:
    """Stamp session/lane attribution on a block tree."""
    block.session_id = ctx.session_id
    block.lane_id = ctx.lane_id
    block.agent_kind = ctx.agent_kind
    block.agent_label = ctx.agent_label
    for child in getattr(block, "children", []):
        _stamp_block_tree(child, ctx)


def _stamp_blocks(blocks, ctx) -> None:
    for block in blocks:
        _stamp_block_tree(block, ctx)


def _sync_stream_footer(widgets) -> None:
    """Push active stream chip state to view_store."""
    view_store = widgets.get("view_store")
    domain_store = widgets.get("domain_store")
    if view_store is None or domain_store is None:
        return
    # // [LAW:one-source-of-truth] Footer stream chips derive from DomainStore.
    view_store.set("streams:active", domain_store.get_active_stream_chips())
    view_store.set("streams:focused", domain_store.get_focused_stream_id() or "")


def _current_turn_from_focus(app_state, domain_store):
    usage_map = app_state.get("current_turn_usage_by_request", {})
    if not isinstance(usage_map, dict):
        return None
    focused = domain_store.get_focused_stream_id() if domain_store is not None else None
    if not focused:
        return None
    usage = usage_map.get(focused)
    return usage if isinstance(usage, dict) else None


def _fallback_session(ctx, state) -> None:
    """Preserve legacy session stamping when stream context has no session."""
    if ctx.session_id:
        return
    current_session = state.get("current_session", "")
    if isinstance(current_session, str) and current_session:
        ctx.session_id = current_session


def _maybe_update_main_session(state, ctx) -> None:
    """Persist current_session from main/seed contexts, never from subagents."""
    if not ctx.session_id:
        return
    current = state.get("current_session", "")
    if not isinstance(current, str):
        current = ""
    # // [LAW:one-source-of-truth] current_session tracks orchestrator session.
    if not current or ctx.agent_kind == "main":
        state["current_session"] = ctx.session_id


def handle_request_headers(event: RequestHeadersEvent, state, widgets, app_state, log_fn):
    """Handle request_headers event.

    Stores request headers in app_state to be included with the request turn.
    """
    headers_dict = event.headers
    pending = app_state.get("pending_request_headers", {})
    if not isinstance(pending, dict):
        pending = {}
    # // [LAW:one-source-of-truth] Headers are keyed by request_id to avoid cross-request races.
    pending[event.request_id] = headers_dict
    app_state["pending_request_headers"] = pending
    log_fn("DEBUG", f"Stored request headers: {len(headers_dict)} headers")
    return app_state


def handle_request(event: RequestBodyEvent, state, widgets, app_state, log_fn):
    """Handle a request event."""
    import time

    body = event.body

    try:
        stream_registry = _get_stream_registry(app_state)
        ctx = stream_registry.register_request(
            event.request_id,
            body if isinstance(body, dict) else {},
            seq=event.seq,
            recv_ns=event.recv_ns,
            session_hint=state.get("current_session", "") if isinstance(state.get("current_session", ""), str) else "",
        )

        # Track last message time for session panel connectivity
        app_state["last_message_time"] = time.monotonic()

        # Capture recent messages for side-channel summarization
        raw_messages = body.get("messages", [])
        recent = app_state.get("recent_messages", [])
        recent.extend(raw_messages)
        app_state["recent_messages"] = recent[-50:]  # rolling window

        # [LAW:one-source-of-truth] Header injection moved into format_request
        pending_headers_all = app_state.get("pending_request_headers", {})
        if not isinstance(pending_headers_all, dict):
            pending_headers_all = {}
        pending_headers = pending_headers_all.pop(event.request_id, None)
        app_state["pending_request_headers"] = pending_headers_all
        blocks = cc_dump.formatting.format_request(body, state, request_headers=pending_headers)
        _stamp_blocks(blocks, ctx)

        domain_store = widgets["domain_store"]
        stats = widgets["stats"]

        # Non-streaming: add turn to domain store (fires callback to ConversationView)
        domain_store.add_turn(blocks)

        # Update stats (only request count and model tracking - not tokens)
        stats.update_stats(requests=state["request_counter"])

        # Keep session panel semantics based on latest request context.
        _maybe_update_main_session(state, ctx)

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
        stream_registry = _get_stream_registry(app_state)
        ctx = stream_registry.mark_streaming(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )
        _fallback_session(ctx, state)

        blocks = cc_dump.formatting.format_response_headers(status_code, headers_dict)
        _stamp_blocks(blocks, ctx)
        _maybe_update_main_session(state, ctx)

        domain_store = widgets["domain_store"]

        domain_store.begin_stream(event.request_id, {
            "agent_kind": ctx.agent_kind,
            "agent_label": ctx.agent_label,
            "lane_id": ctx.lane_id,
        })

        # Append response header blocks (empty list is safe)
        for block in blocks:
            domain_store.append_stream_block(event.request_id, block)

        if blocks:  # Only log if blocks were actually produced
            log_fn(
                "DEBUG",
                f"Displayed response headers: HTTP {status_code}, {len(headers_dict)} headers",
            )
        _sync_stream_footer(widgets)
    except Exception as e:
        log_fn("ERROR", f"Error handling response headers: {e}")
        raise

    return app_state


def handle_response_event(event: ResponseSSEEvent, state, widgets, app_state, log_fn):
    """Handle a response SSE event."""
    sse_event = event.sse_event

    try:
        stream_registry = _get_stream_registry(app_state)
        ctx = stream_registry.mark_streaming(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )
        _fallback_session(ctx, state)
        if isinstance(sse_event, ToolUseBlockStartEvent) and sse_event.name == "Task":
            ctx = stream_registry.note_task_tool_use(
                event.request_id,
                sse_event.id,
                seq=event.seq,
                recv_ns=event.recv_ns,
            )
            _fallback_session(ctx, state)
        blocks = cc_dump.formatting.format_response_event(sse_event)
        _stamp_blocks(blocks, ctx)
        _maybe_update_main_session(state, ctx)

        domain_store = widgets["domain_store"]
        stats = widgets["stats"]

        domain_store.begin_stream(event.request_id, {
            "agent_kind": ctx.agent_kind,
            "agent_label": ctx.agent_label,
            "lane_id": ctx.lane_id,
        })

        for block in blocks:
            # Append to domain store (fires callback to ConversationView)
            domain_store.append_stream_block(event.request_id, block)

            # Extract stats from message_start and message_delta
            if isinstance(block, cc_dump.formatting.StreamInfoBlock):
                stats.update_stats(model=block.model)
                # Extract usage data from message_start for current turn tracking
                if isinstance(sse_event, MessageStartEvent):
                    usage = sse_event.message.usage
                    usage_by_request = app_state.get("current_turn_usage_by_request", {})
                    if not isinstance(usage_by_request, dict):
                        usage_by_request = {}
                    current_turn = usage_by_request.get(event.request_id, {})
                    current_turn["input_tokens"] = usage.input_tokens
                    current_turn["cache_read_tokens"] = usage.cache_read_input_tokens
                    current_turn["cache_creation_tokens"] = usage.cache_creation_input_tokens
                    current_turn["model"] = block.model
                    usage_by_request[event.request_id] = current_turn
                    app_state["current_turn_usage_by_request"] = usage_by_request

            elif isinstance(sse_event, MessageDeltaEvent):
                # Track output tokens for current turn
                usage_by_request = app_state.get("current_turn_usage_by_request", {})
                if not isinstance(usage_by_request, dict):
                    usage_by_request = {}
                current_turn = usage_by_request.get(event.request_id, {})
                current_turn["output_tokens"] = sse_event.output_tokens
                usage_by_request[event.request_id] = current_turn
                app_state["current_turn_usage_by_request"] = usage_by_request

        # Refresh stats with the currently focused active stream, if any.
        analytics_store = widgets.get("analytics_store")
        if analytics_store is not None:
            stats.refresh_from_store(
                analytics_store,
                current_turn=_current_turn_from_focus(app_state, domain_store),
            )
        _sync_stream_footer(widgets)
    except Exception as e:
        log_fn("ERROR", f"Error handling response event: {e}")
        raise

    return app_state


def handle_response_done(event: ResponseDoneEvent, state, widgets, app_state, log_fn):
    """Handle response_done event."""
    try:
        stream_registry = _get_stream_registry(app_state)
        ctx = stream_registry.mark_done(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )
        _fallback_session(ctx, state)
        domain_store = widgets["domain_store"]
        conv = widgets["conv"]
        stats = widgets["stats"]
        filters = widgets["filters"]
        refresh_callbacks = widgets.get("refresh_callbacks", {})
        analytics_store = widgets.get("analytics_store")

        # Finalize request-scoped stream in domain store (fires callback to ConversationView).
        _ = domain_store.finalize_stream(event.request_id)

        # Clear current turn usage for this request.
        usage_by_request = app_state.get("current_turn_usage_by_request", {})
        if isinstance(usage_by_request, dict):
            usage_by_request.pop(event.request_id, None)
            app_state["current_turn_usage_by_request"] = usage_by_request
        # Legacy key retained for backward compatibility with old app_state shape.
        app_state["current_turn_usage"] = {}
        _maybe_update_main_session(state, ctx)

        # Refresh stats panel from analytics store (merges current turn if streaming)
        if analytics_store is not None:
            stats.refresh_from_store(
                analytics_store,
                current_turn=_current_turn_from_focus(app_state, domain_store),
            )

        # Re-render to show cache data in budget blocks
        budget_vis = filters.get("metadata", cc_dump.formatting.HIDDEN)
        if budget_vis.visible:
            conv.rerender(filters)

        # Update economics, timeline, and session panels
        if "refresh_economics" in refresh_callbacks:
            refresh_callbacks["refresh_economics"]()
        if "refresh_timeline" in refresh_callbacks:
            refresh_callbacks["refresh_timeline"]()
        if "refresh_session" in refresh_callbacks:
            refresh_callbacks["refresh_session"]()

        _sync_stream_footer(widgets)
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
    block.session_id = state.get("current_session", "")

    domain_store = widgets["domain_store"]

    # Single block, non-streaming: add directly
    domain_store.add_turn([block])

    return app_state


def handle_proxy_error(event: ProxyErrorEvent, state, widgets, app_state, log_fn):
    """Handle a proxy_error event."""
    err = event.error

    log_fn("ERROR", f"Proxy error: {err}")

    block = cc_dump.formatting.ProxyErrorBlock(error=err)
    block.session_id = state.get("current_session", "")

    domain_store = widgets["domain_store"]

    # Single block, non-streaming: add directly
    domain_store.add_turn([block])

    return app_state


def handle_log(event: LogEvent, state, widgets, app_state, log_fn):
    """Handle a log event."""
    log_fn("DEBUG", f"HTTP {event.method} {event.path} -> {event.status}")
    return app_state


def handle_response_non_streaming(event: ResponseNonStreamingEvent, state, widgets, app_state, log_fn):
    """Handle a complete (non-streaming) HTTP response.

    // [LAW:one-source-of-truth] Uses the same format_complete_response as replay.
    """
    try:
        stream_registry = _get_stream_registry(app_state)
        ctx = stream_registry.mark_done(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )
        _fallback_session(ctx, state)
        domain_store = widgets["domain_store"]
        stats = widgets["stats"]
        refresh_callbacks = widgets.get("refresh_callbacks", {})
        analytics_store = widgets.get("analytics_store")

        # Response header blocks
        response_blocks = list(
            cc_dump.formatting.format_response_headers(event.status_code, event.headers)
        )

        # Complete message blocks
        response_blocks.extend(
            cc_dump.formatting.format_complete_response(event.body)
        )

        _stamp_blocks(response_blocks, ctx)
        _maybe_update_main_session(state, ctx)

        domain_store.add_turn(response_blocks)

        # Refresh stats and panels (same as response_done)
        if analytics_store is not None:
            stats.refresh_from_store(analytics_store, current_turn=None)
        for cb_name in ("refresh_economics", "refresh_timeline", "refresh_session"):
            cb = refresh_callbacks.get(cb_name)
            if cb:
                cb()

        _sync_stream_footer(widgets)
        log_fn("DEBUG", f"Complete response: HTTP {event.status_code}")
    except Exception as e:
        log_fn("ERROR", f"Error handling complete response: {e}")
        raise

    return app_state


def handle_response_complete(event: ResponseCompleteEvent, state, widgets, app_state, log_fn):
    """Handle reconstructed complete response event.

    UI rendering is driven by RESPONSE_EVENT/RESPONSE_DONE and RESPONSE_NON_STREAMING.
    This event is consumed by analytics and persistence subscribers.
    """
    _ = _get_stream_registry(app_state).ensure_context(
        event.request_id,
        seq=event.seq,
        recv_ns=event.recv_ns,
    )
    return app_state


def _noop(event, state, widgets, app_state, log_fn) -> dict:
    """No-op handler for events that need no action."""
    return app_state


# [LAW:dataflow-not-control-flow] Event dispatch table keyed by PipelineEventKind
EVENT_HANDLERS: dict[PipelineEventKind, EventHandler] = {
    PipelineEventKind.REQUEST_HEADERS: handle_request_headers,
    PipelineEventKind.REQUEST: handle_request,
    PipelineEventKind.RESPONSE_HEADERS: handle_response_headers,
    PipelineEventKind.RESPONSE_EVENT: handle_response_event,
    PipelineEventKind.RESPONSE_COMPLETE: handle_response_complete,
    PipelineEventKind.RESPONSE_NON_STREAMING: handle_response_non_streaming,
    PipelineEventKind.RESPONSE_DONE: handle_response_done,
    PipelineEventKind.ERROR: handle_error,
    PipelineEventKind.PROXY_ERROR: handle_proxy_error,
    PipelineEventKind.LOG: handle_log,
}
