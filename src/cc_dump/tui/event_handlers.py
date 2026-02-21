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
    ResponseProgressEvent,
    ResponseNonStreamingEvent,
    ResponseCompleteEvent,
    ResponseDoneEvent,
    ErrorEvent,
    ProxyErrorEvent,
    LogEvent,
    sse_progress_payload,
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


def _sync_active_stream_attribution(widgets, stream_registry) -> None:
    """Restamp active stream blocks/meta from canonical stream registry contexts."""
    domain_store = widgets.get("domain_store")
    if domain_store is None:
        return
    # // [LAW:one-source-of-truth] request_id -> attribution mapping is owned by StreamRegistry.
    for request_id in domain_store.get_active_stream_ids():
        ctx = stream_registry.get(request_id)
        if ctx is None:
            continue
        domain_store.restamp_stream(
            request_id,
            session_id=ctx.session_id,
            lane_id=ctx.lane_id,
            agent_kind=ctx.agent_kind,
            agent_label=ctx.agent_label,
        )


def _store_response_meta(app_state, request_id: str, status_code: int, headers: dict) -> None:
    """Store response headers/status by request_id for complete-response finalization."""
    by_request = app_state.get("response_meta_by_request", {})
    if not isinstance(by_request, dict):
        by_request = {}
    by_request[request_id] = {
        "status_code": status_code,
        "headers": dict(headers) if isinstance(headers, dict) else {},
    }
    app_state["response_meta_by_request"] = by_request


def _pop_response_meta(app_state, request_id: str) -> tuple[int, dict]:
    """Pop response headers/status for request_id."""
    by_request = app_state.get("response_meta_by_request", {})
    if not isinstance(by_request, dict):
        by_request = {}
    payload = by_request.pop(request_id, None)
    app_state["response_meta_by_request"] = by_request

    if not isinstance(payload, dict):
        return 0, {}
    status_code = payload.get("status_code", 0)
    if not isinstance(status_code, int):
        status_code = 0
    headers = payload.get("headers", {})
    if not isinstance(headers, dict):
        headers = {}
    return status_code, headers


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


def _clear_current_turn_usage(app_state, request_id: str) -> None:
    """Clear per-request streaming usage tracking."""
    usage_by_request = app_state.get("current_turn_usage_by_request", {})
    if isinstance(usage_by_request, dict):
        usage_by_request.pop(request_id, None)
        app_state["current_turn_usage_by_request"] = usage_by_request
    # Legacy key retained for backward compatibility with old app_state shape.
    app_state["current_turn_usage"] = {}


def _refresh_post_response(state, widgets, app_state, *, rerender_budget: bool = True) -> None:
    """Refresh stats/panels after a response completion path."""
    domain_store = widgets["domain_store"]
    stats = widgets["stats"]
    conv = widgets["conv"]
    filters = widgets["filters"]
    refresh_callbacks = widgets.get("refresh_callbacks", {})
    analytics_store = widgets.get("analytics_store")

    if analytics_store is not None:
        stats.refresh_from_store(
            analytics_store,
            current_turn=_current_turn_from_focus(app_state, domain_store),
        )

    if rerender_budget:
        budget_vis = filters.get("metadata", cc_dump.formatting.HIDDEN)
        if budget_vis.visible:
            conv.rerender(filters)

    for cb_name in ("refresh_economics", "refresh_timeline", "refresh_session"):
        cb = refresh_callbacks.get(cb_name)
        if cb:
            cb()
    _sync_stream_footer(widgets)


def _handle_complete_response_payload(
    *,
    request_id: str,
    complete_body: dict,
    state,
    widgets,
    app_state,
    seq: int = 0,
    recv_ns: int = 0,
) -> dict[str, object]:
    """Canonical response finalization path for both streaming and non-streaming transport."""
    stream_registry = _get_stream_registry(app_state)
    ctx = stream_registry.mark_done(
        request_id,
        seq=seq,
        recv_ns=recv_ns,
    )
    _fallback_session(ctx, state)

    status_code, headers_dict = _pop_response_meta(app_state, request_id)
    response_blocks: list = []
    if status_code > 0 or headers_dict:
        response_blocks.extend(
            cc_dump.formatting.format_response_headers(status_code or 200, headers_dict)
        )
    response_blocks.extend(cc_dump.formatting.format_complete_response(complete_body))

    _stamp_blocks(response_blocks, ctx)
    _maybe_update_main_session(state, ctx)

    domain_store = widgets["domain_store"]
    if domain_store.get_stream_blocks(request_id):
        domain_store.finalize_stream_with_blocks(request_id, response_blocks)
    else:
        domain_store.add_turn(response_blocks)

    _clear_current_turn_usage(app_state, request_id)
    _refresh_post_response(state, widgets, app_state, rerender_budget=True)
    return app_state


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
        _sync_active_stream_attribution(widgets, stream_registry)

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
        _store_response_meta(app_state, event.request_id, status_code, headers_dict)
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
        _sync_active_stream_attribution(widgets, stream_registry)

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


def _upsert_current_turn_usage(app_state, request_id: str, progress: ResponseProgressEvent) -> None:
    """Merge progress usage/model data into current_turn_usage_by_request."""
    usage_by_request = app_state.get("current_turn_usage_by_request", {})
    if not isinstance(usage_by_request, dict):
        usage_by_request = {}
    current_turn = usage_by_request.get(request_id, {})
    if not isinstance(current_turn, dict):
        current_turn = {}

    if progress.model:
        current_turn["model"] = progress.model
    if progress.input_tokens is not None:
        current_turn["input_tokens"] = progress.input_tokens
    if progress.cache_read_input_tokens is not None:
        current_turn["cache_read_tokens"] = progress.cache_read_input_tokens
    if progress.cache_creation_input_tokens is not None:
        current_turn["cache_creation_tokens"] = progress.cache_creation_input_tokens
    if progress.output_tokens is not None:
        current_turn["output_tokens"] = progress.output_tokens

    usage_by_request[request_id] = current_turn
    app_state["current_turn_usage_by_request"] = usage_by_request


def handle_response_progress(event: ResponseProgressEvent, state, widgets, app_state, log_fn):
    """Handle transport-normalized streaming progress hints."""
    try:
        stream_registry = _get_stream_registry(app_state)
        ctx = stream_registry.mark_streaming(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )
        _fallback_session(ctx, state)
        if event.task_tool_use_id:
            ctx = stream_registry.note_task_tool_use(
                event.request_id,
                event.task_tool_use_id,
                seq=event.seq,
                recv_ns=event.recv_ns,
            )
            _fallback_session(ctx, state)

        _maybe_update_main_session(state, ctx)

        domain_store = widgets["domain_store"]
        stats = widgets["stats"]

        domain_store.begin_stream(event.request_id, {
            "agent_kind": ctx.agent_kind,
            "agent_label": ctx.agent_label,
            "lane_id": ctx.lane_id,
        })

        if event.delta_text:
            block = cc_dump.formatting.TextDeltaBlock(
                content=event.delta_text,
                category=cc_dump.formatting.Category.ASSISTANT,
            )
            _stamp_block_tree(block, ctx)
            domain_store.append_stream_block(event.request_id, block)

        if event.model:
            stats.update_stats(model=event.model)

        _upsert_current_turn_usage(app_state, event.request_id, event)
        _sync_active_stream_attribution(widgets, stream_registry)

        # Refresh stats with the currently focused active stream, if any.
        analytics_store = widgets.get("analytics_store")
        if analytics_store is not None:
            stats.refresh_from_store(
                analytics_store,
                current_turn=_current_turn_from_focus(app_state, domain_store),
            )
        _sync_stream_footer(widgets)
    except Exception as e:
        log_fn("ERROR", f"Error handling response progress: {e}")
        raise

    return app_state


def handle_response_event(event: ResponseSSEEvent, state, widgets, app_state, log_fn):
    """Compatibility shim for legacy SSE events.

    // [LAW:locality-or-seam] Legacy SSE transport is translated at this seam
    // into ResponseProgressEvent so downstream handlers stay transport-agnostic.
    """
    payload = sse_progress_payload(event.sse_event)
    if payload is None:
        return app_state
    progress = ResponseProgressEvent(
        request_id=event.request_id,
        seq=event.seq,
        recv_ns=event.recv_ns,
        **payload,
    )
    return handle_response_progress(progress, state, widgets, app_state, log_fn)


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
        _maybe_update_main_session(state, ctx)

        # [LAW:single-enforcer] RESPONSE_COMPLETE is canonical finalization path.
        # RESPONSE_DONE only handles rare fallback where complete payload never arrived.
        if domain_store.get_stream_blocks(event.request_id):
            _ = _pop_response_meta(app_state, event.request_id)
            _ = domain_store.finalize_stream(event.request_id)
            _clear_current_turn_usage(app_state, event.request_id)
            _refresh_post_response(state, widgets, app_state, rerender_budget=True)
            log_fn("DEBUG", "Response done fallback finalized active stream")
            return app_state

        _ = _pop_response_meta(app_state, event.request_id)
        _clear_current_turn_usage(app_state, event.request_id)
        _sync_stream_footer(widgets)
        log_fn("DEBUG", "Response done acknowledged")
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
    """Normalize non-streaming transport into canonical complete-response path."""
    try:
        _store_response_meta(app_state, event.request_id, event.status_code, event.headers)
        _handle_complete_response_payload(
            request_id=event.request_id,
            complete_body=event.body,
            state=state,
            widgets=widgets,
            app_state=app_state,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )
        log_fn("DEBUG", f"Complete response via non-streaming transport: HTTP {event.status_code}")
    except Exception as e:
        log_fn("ERROR", f"Error handling complete response: {e}")
        raise

    return app_state


def handle_response_complete(event: ResponseCompleteEvent, state, widgets, app_state, log_fn):
    """Handle reconstructed complete response event as the canonical UI path."""
    _ = _handle_complete_response_payload(
        request_id=event.request_id,
        complete_body=event.body,
        state=state,
        widgets=widgets,
        app_state=app_state,
        seq=event.seq,
        recv_ns=event.recv_ns,
    )
    log_fn("DEBUG", "Complete response finalized")
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
    PipelineEventKind.RESPONSE_PROGRESS: handle_response_progress,
    PipelineEventKind.RESPONSE_COMPLETE: handle_response_complete,
    PipelineEventKind.RESPONSE_NON_STREAMING: handle_response_non_streaming,
    PipelineEventKind.RESPONSE_DONE: handle_response_done,
    PipelineEventKind.ERROR: handle_error,
    PipelineEventKind.PROXY_ERROR: handle_proxy_error,
    PipelineEventKind.LOG: handle_log,
}
