"""Event handling logic - pure functions for processing proxy events.

This module is RELOADABLE. It contains all the logic for what to do when
events arrive from the proxy. The app.py module calls into these functions
but the actual behavior can be hot-swapped.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import cc_dump.core.analysis
import cc_dump.core.formatting
import cc_dump.tui.stream_registry
from cc_dump.pipeline.event_types import (
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

from cc_dump.core.formatting_impl import ProviderRuntimeState

EventHandler = Callable[
    [object, dict[str, object], dict[str, object], dict[str, object], Callable[[str, str], None]],
    dict[str, object],
]

_CAPACITY_ENV_VAR = "CC_DUMP_TOKEN_CAPACITY"
_CACHED_CAPACITY_RAW: str | None = None
_CACHED_CAPACITY_TOTAL: int | None = None


def _get_stream_registry(app_state):
    """Get or create the stream registry in app_state."""
    reg = app_state.get("stream_registry")
    if reg is None:
        reg = cc_dump.tui.stream_registry.StreamRegistry()
        app_state["stream_registry"] = reg
    return reg



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


def _clear_current_turn_usage(app_state, request_id: str) -> None:
    """Clear per-request streaming usage tracking."""
    usage_by_request = app_state.get("current_turn_usage_by_request", {})
    if isinstance(usage_by_request, dict):
        usage_by_request.pop(request_id, None)
        app_state["current_turn_usage_by_request"] = usage_by_request


def _focused_current_turn_usage(app_state, domain_store) -> dict | None:
    """Resolve in-progress usage for the currently focused stream in domain_store.

    // [LAW:one-source-of-truth] Focused request_id resolves once from DomainStore.
    """
    usage_by_request = app_state.get("current_turn_usage_by_request", {})
    if not isinstance(usage_by_request, dict):
        return None
    focused_getter = getattr(domain_store, "get_focused_stream_id", None)
    focused_request_id = focused_getter() if callable(focused_getter) else None
    if not focused_request_id:
        return None
    current_turn = usage_by_request.get(focused_request_id)
    return current_turn if isinstance(current_turn, dict) else None


def _get_capacity_total() -> int:
    """Get parsed token capacity with memoized env-var parsing."""
    global _CACHED_CAPACITY_RAW, _CACHED_CAPACITY_TOTAL

    capacity_raw = str(os.environ.get(_CAPACITY_ENV_VAR, "") or "").strip()
    if capacity_raw == _CACHED_CAPACITY_RAW and _CACHED_CAPACITY_TOTAL is not None:
        return _CACHED_CAPACITY_TOTAL

    try:
        capacity_total = int(capacity_raw) if capacity_raw else 0
    except ValueError:
        capacity_total = 0

    _CACHED_CAPACITY_RAW = capacity_raw
    _CACHED_CAPACITY_TOTAL = capacity_total
    return capacity_total


def _with_capacity_summary(snapshot: dict[str, object]) -> dict[str, object]:
    """Attach optional token-capacity summary fields to analytics snapshot."""
    summary = snapshot.get("summary", {})
    summary_dict = dict(summary) if isinstance(summary, dict) else {}

    capacity_total = _get_capacity_total()

    if capacity_total > 0:
        used_tokens = int(summary_dict.get("total_tokens", 0))
        remaining_tokens = max(0, capacity_total - used_tokens)
        used_pct = min(100.0, (used_tokens / capacity_total) * 100.0)
        summary_dict["capacity_total"] = capacity_total
        summary_dict["capacity_used"] = used_tokens
        summary_dict["capacity_remaining"] = remaining_tokens
        summary_dict["capacity_used_pct"] = used_pct

    return {
        **snapshot,
        "summary": summary_dict,
    }


def _refresh_stats_snapshot(widgets, app_state) -> None:
    """Recompute and publish canonical stats panel snapshot.

    // [LAW:single-enforcer] This is the sole writer for panel:stats_snapshot.
    """
    view_store = widgets.get("view_store")
    if view_store is None:
        return
    analytics_store = widgets.get("analytics_store")
    if analytics_store is None:
        view_store.set("panel:stats_snapshot", {"summary": {}, "timeline": [], "models": []})
        return

    domain_store = widgets.get("domain_store")
    snapshot = analytics_store.get_dashboard_snapshot(
        current_turn=_focused_current_turn_usage(app_state, domain_store)
    )
    view_store.set("panel:stats_snapshot", _with_capacity_summary(snapshot))


_last_stats_refresh_ns: int = 0
_STATS_REFRESH_INTERVAL_NS = 1_000_000_000  # 1 second


def _refresh_stats_snapshot_throttled(widgets, app_state) -> None:
    """Throttled variant for streaming hot path — at most once per second."""
    global _last_stats_refresh_ns
    now = time.monotonic_ns()
    if now - _last_stats_refresh_ns < _STATS_REFRESH_INTERVAL_NS:
        return
    _last_stats_refresh_ns = now
    _refresh_stats_snapshot(widgets, app_state)


def _refresh_post_response(state, widgets, app_state, *, rerender_budget: bool = True) -> None:
    """Refresh derived UI state after a response completion path."""
    conv = widgets["conv"]
    filters = widgets["filters"]

    if rerender_budget:
        budget_vis = filters.get("metadata", cc_dump.core.formatting.HIDDEN)
        if budget_vis.visible:
            conv.rerender(filters)
    _refresh_stats_snapshot(widgets, app_state)


def _reconstruct_request_blocks(
    provisional: dict,
    complete_body: dict,
    state: ProviderRuntimeState,
    domain_store,
) -> list:
    """Rebuild request blocks with cache zone annotations if usage data is available.

    Returns the original turn blocks when cache zones cannot be computed.
    """
    usage = complete_body.get("usage", {})
    cache_zones = (
        cc_dump.core.analysis.compute_cache_zones(
            provisional["body"],
            cache_read=usage.get("cache_read_input_tokens", 0),
            cache_creation=usage.get("cache_creation_input_tokens", 0),
            input_tokens=usage.get("input_tokens", 0),
        )
        if usage
        else {}
    )
    if not cache_zones:
        return list(domain_store.get_turn_blocks(provisional["turn_index"]))

    # Compensate for request_counter increment in format_request —
    # reconstruction replaces an existing turn, not a new request.
    state.request_counter -= 1
    return cc_dump.core.formatting.format_request_for_provider(
        provisional["provider"],
        provisional["body"],
        state,
        request_headers=provisional.get("request_headers"),
        cache_zones=cache_zones,
    )


def _commit_combined_turn(
    request_id: str,
    turn_index: int,
    request_blocks: list,
    response_blocks: list,
    domain_store,
) -> None:
    """Commit combined request+response blocks into a single conversation turn.

    // [LAW:one-source-of-truth] Request+response is a single conversation turn.
    """
    combined = request_blocks + response_blocks
    if domain_store.get_stream_blocks(request_id):
        domain_store.finalize_stream_replacing_turn(request_id, turn_index, combined)
    else:
        domain_store.replace_turn(turn_index, combined)


def _handle_complete_response_payload(
    *,
    request_id: str,
    complete_body: dict,
    state: ProviderRuntimeState,
    widgets,
    app_state,
    seq: int = 0,
    recv_ns: int = 0,
    provider: str = "anthropic",
) -> dict[str, object]:
    """Canonical response finalization path for both streaming and non-streaming transport."""
    stream_registry = _get_stream_registry(app_state)
    stream_registry.mark_done(request_id, seq=seq, recv_ns=recv_ns)

    domain_store = widgets["domain_store"]

    # // [LAW:one-source-of-truth] Popping provisional data stored in handle_request.
    provisional = app_state.get("provisional_requests", {}).pop(request_id, None)

    # ── Build request blocks (with cache zones if usage available) ──
    request_blocks: list = []
    turn_index = provisional["turn_index"] if provisional else -1
    if provisional:
        request_blocks = _reconstruct_request_blocks(provisional, complete_body, state, domain_store)

    # ── Build response blocks ──
    status_code, headers_dict = _pop_response_meta(app_state, request_id)
    response_blocks: list = []
    if status_code > 0 or headers_dict:
        response_blocks.extend(
            cc_dump.core.formatting.format_response_headers(status_code or 200, headers_dict)
        )
    response_blocks.extend(cc_dump.core.formatting.format_complete_response_for_provider(provider, complete_body))

    # ── Combine and replace, or fall back to separate turn ──
    if provisional and 0 <= turn_index < domain_store.completed_count:
        _commit_combined_turn(request_id, turn_index, request_blocks, response_blocks, domain_store)
    else:
        # No provisional data or stale index — graceful degradation
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
    body = event.body

    try:
        stream_registry = _get_stream_registry(app_state)
        stream_registry.register_request(
            event.request_id,
            body if isinstance(body, dict) else {},
            seq=event.seq,
            recv_ns=event.recv_ns,
            session_hint=state.current_session or "",
        )

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
        provider = event.provider
        blocks = cc_dump.core.formatting.format_request_for_provider(provider, body, state, request_headers=pending_headers)

        domain_store = widgets["domain_store"]
        # Non-streaming: add turn to domain store (fires callback to ConversationView)
        turn_index = domain_store.add_turn(blocks)
        # Store provisional request data for cache zone reconstruction on response.
        # // [LAW:one-source-of-truth] Popped in _handle_complete_response_payload.
        provisional = app_state.setdefault("provisional_requests", {})
        provisional[event.request_id] = {
            "turn_index": turn_index,
            "body": body,
            "provider": provider,
            "request_headers": pending_headers,
        }
        _refresh_stats_snapshot(widgets, app_state)

        log_fn("DEBUG", f"Request #{state.request_counter} processed")
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
        stream_registry.mark_streaming(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )

        blocks = cc_dump.core.formatting.format_response_headers(status_code, headers_dict)

        domain_store = widgets["domain_store"]

        domain_store.begin_stream(event.request_id)

        # Append response header blocks (empty list is safe)
        for block in blocks:
            domain_store.append_stream_block(event.request_id, block)

        if blocks:  # Only log if blocks were actually produced
            log_fn(
                "DEBUG",
                f"Displayed response headers: HTTP {status_code}, {len(headers_dict)} headers",
            )
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
        stream_registry.mark_streaming(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )

        domain_store = widgets["domain_store"]
        domain_store.begin_stream(event.request_id)

        if event.delta_text:
            block = cc_dump.core.formatting.TextDeltaBlock(
                content=event.delta_text,
                category=cc_dump.core.formatting.Category.ASSISTANT,
            )
            domain_store.append_stream_block(event.request_id, block)

        _upsert_current_turn_usage(app_state, event.request_id, event)
        _refresh_stats_snapshot_throttled(widgets, app_state)
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
        stream_registry.mark_done(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )
        domain_store = widgets["domain_store"]

        # Clean up provisional request data so it doesn't leak.
        _ = app_state.get("provisional_requests", {}).pop(event.request_id, None)

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
        _refresh_stats_snapshot(widgets, app_state)
        log_fn("DEBUG", "Response done acknowledged")
    except Exception as e:
        log_fn("ERROR", f"Error handling response done: {e}")
        raise

    return app_state


def handle_error(event: ErrorEvent, state, widgets, app_state, log_fn):
    """Handle an error event."""
    code, reason = event.code, event.reason

    log_fn("ERROR", f"HTTP Error {code}: {reason}")

    block = cc_dump.core.formatting.ErrorBlock(code=code, reason=reason)

    domain_store = widgets["domain_store"]

    # Single block, non-streaming: add directly
    domain_store.add_turn([block])

    return app_state


def handle_proxy_error(event: ProxyErrorEvent, state, widgets, app_state, log_fn):
    """Handle a proxy_error event."""
    err = event.error

    log_fn("ERROR", f"Proxy error: {err}")

    block = cc_dump.core.formatting.ProxyErrorBlock(error=err)

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
            provider=event.provider,
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
        provider=event.provider,
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
