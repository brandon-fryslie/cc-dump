"""Event handling logic - pure functions for processing proxy events.

// [LAW:single-enforcer] Per-request state lives on Request records in the
//   RequestRegistry, not in a stringly-typed app_state bag.
// [LAW:dataflow-not-control-flow] Handlers read/write typed Request fields
//   instead of branching on `isinstance(app_state["key"], dict)`.

This module is RELOADABLE. It contains all the logic for what to do when
events arrive from the proxy. The app.py module calls into these functions
but the actual behavior can be hot-swapped.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import cc_dump.core.analysis
import cc_dump.core.formatting
import cc_dump.tui.request_registry
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
    [object, ProviderRuntimeState, dict[str, object], Callable[[str, str], None]],
    None,
]

_CAPACITY_ENV_VAR = "CC_DUMP_TOKEN_CAPACITY"
_CACHED_CAPACITY_RAW: str | None = None
_CACHED_CAPACITY_TOTAL: int | None = None


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


def _focused_stream_id(domain_store) -> str | None:
    """// [LAW:dataflow-not-control-flow] Absent domain store → no focused id."""
    if domain_store is None:
        return None
    return domain_store.get_focused_stream_id()


def _ensure_dict(value) -> dict:
    """// [LAW:single-enforcer] Single place that normalizes unknown-shape headers."""
    if isinstance(value, dict):
        return dict(value)
    return {}


def _refresh_stats_snapshot(context) -> None:
    """Recompute and publish canonical stats panel snapshot.

    // [LAW:single-enforcer] This is the sole writer for panel:stats_snapshot.
    """
    view_store = context.get("view_store")
    if view_store is None:
        return
    analytics_store = context.get("analytics_store")
    if analytics_store is None:
        view_store.set("panel:stats_snapshot", {"summary": {}, "timeline": [], "models": []})
        return

    request_registry = context["request_registry"]
    focused_id = _focused_stream_id(context.get("domain_store"))
    snapshot = analytics_store.get_dashboard_snapshot(
        current_turn=request_registry.focused_usage(focused_id)
    )
    view_store.set("panel:stats_snapshot", _with_capacity_summary(snapshot))


_last_stats_refresh_ns: int = 0
_STATS_REFRESH_INTERVAL_NS = 1_000_000_000  # 1 second


def _refresh_stats_snapshot_throttled(context) -> None:
    """Throttled variant for streaming hot path — at most once per second."""
    global _last_stats_refresh_ns
    now = time.monotonic_ns()
    if now - _last_stats_refresh_ns < _STATS_REFRESH_INTERVAL_NS:
        return
    _last_stats_refresh_ns = now
    _refresh_stats_snapshot(context)


def _refresh_post_response(state, context, *, rerender_budget: bool = True) -> None:
    """Refresh derived UI state after a response completion path."""
    conv = context["conv"]
    filters = context["filters"]

    if rerender_budget:
        budget_vis = filters.get("metadata", cc_dump.core.formatting.HIDDEN)
        if budget_vis.visible:
            conv.rerender(filters)
    _refresh_stats_snapshot(context)


def _annotate_cache_zones(blocks: list, cache_zones: dict[str, object]) -> list:
    """Annotate existing request blocks with cache zone metadata in-place.

    // [LAW:dataflow-not-control-flow] Zones are data annotations on existing blocks,
    // not control flow that rebuilds the block tree.
    """
    for block in blocks:
        block_type = type(block).__name__
        zone_key: str | None = None
        if block_type == "ToolDefsSection":
            zone_key = "tools"
        elif block_type == "SystemSection":
            zone_key = "system"
        elif block_type == "MessageBlock":
            zone_key = f"message:{block.msg_index}"
        if zone_key is not None and zone_key in cache_zones:
            if block.metadata is None:
                block.metadata = {}
            block.metadata["cache"] = cache_zones[zone_key].value
    return blocks


def _get_request_blocks_with_zones(
    req: "cc_dump.tui.request_registry.Request",
    complete_body: dict,
    domain_store,
) -> list:
    """Get request blocks annotated with cache zone metadata if usage data is available.

    Returns the original turn blocks, annotated in-place with cache zones.
    No state mutation — overlap-safe for concurrent requests.
    """
    blocks = list(domain_store.get_turn_blocks(req.turn_index))
    # // [LAW:single-enforcer] Coerce None → {} at boundary.
    usage = complete_body.get("usage") or {}
    if not usage:
        return blocks
    cache_zones = cc_dump.core.analysis.compute_cache_zones(
        req.body,
        cache_read=usage.get("cache_read_input_tokens", 0),
        cache_creation=usage.get("cache_creation_input_tokens", 0),
        input_tokens=usage.get("input_tokens", 0),
    )
    if not cache_zones:
        return blocks
    return _annotate_cache_zones(blocks, cache_zones)


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


@dataclass
class _CompletionFrame:
    """Typed snapshot of the pending Request state at complete-response time.

    // [LAW:dataflow-not-control-flow] Callers read named fields; they never
    //   ask "is the request record present?".
    """

    turn_index: int
    status_code: int
    headers_dict: dict


def _completion_frame(req) -> _CompletionFrame:
    if req is None:
        return _CompletionFrame(turn_index=-1, status_code=0, headers_dict={})
    return _CompletionFrame(
        turn_index=req.turn_index,
        status_code=req.response_status,
        headers_dict=req.response_headers,
    )


def _build_response_blocks(frame: _CompletionFrame, provider: str, complete_body: dict) -> list:
    blocks: list = []
    if frame.status_code > 0 or frame.headers_dict:
        blocks.extend(
            cc_dump.core.formatting.format_response_headers(
                frame.status_code or 200, frame.headers_dict
            )
        )
    blocks.extend(
        cc_dump.core.formatting.format_complete_response_for_provider(provider, complete_body)
    )
    return blocks


def _commit_or_fallback(
    request_id: str,
    frame: _CompletionFrame,
    request_blocks: list,
    response_blocks: list,
    domain_store,
) -> None:
    """Single enforcer for "reuse provisional turn or fall back to a new turn"."""
    if 0 <= frame.turn_index < domain_store.completed_count:
        _commit_combined_turn(
            request_id, frame.turn_index, request_blocks, response_blocks, domain_store
        )
        return
    if domain_store.get_stream_blocks(request_id):
        domain_store.finalize_stream_with_blocks(request_id, response_blocks)
        return
    domain_store.add_turn(response_blocks)


def _handle_complete_response_payload(
    *,
    request_id: str,
    complete_body: dict,
    state: ProviderRuntimeState,
    context,
    seq: int = 0,
    recv_ns: int = 0,
    provider: str = "anthropic",
) -> None:
    """Canonical response finalization path for both streaming and non-streaming transport."""
    stream_registry = context["stream_registry"]
    stream_registry.mark_done(request_id, seq=seq, recv_ns=recv_ns)

    domain_store = context["domain_store"]
    request_registry = context["request_registry"]

    # // [LAW:single-enforcer] Registry owns the Request record; we pop it on complete.
    req = request_registry.pop(request_id)
    frame = _completion_frame(req)

    request_blocks: list = []
    if req is not None and frame.turn_index >= 0:
        request_blocks = _get_request_blocks_with_zones(req, complete_body, domain_store)

    response_blocks = _build_response_blocks(frame, provider, complete_body)

    _commit_or_fallback(request_id, frame, request_blocks, response_blocks, domain_store)

    _refresh_post_response(state, context, rerender_budget=True)


def handle_request_headers(event: RequestHeadersEvent, state, context, log_fn) -> None:
    """Handle request_headers event.

    Stores headers on the Request record for the body handler to inject.
    """
    req = context["request_registry"].get_or_create(event.request_id)
    req.pending_headers = event.headers
    log_fn("DEBUG", f"Stored request headers: {len(event.headers)} headers")


def handle_request(event: RequestBodyEvent, state, context, log_fn) -> None:
    """Handle a request event."""
    body = event.body

    try:
        stream_registry = context["stream_registry"]
        stream_registry.register_request(
            event.request_id,
            body if isinstance(body, dict) else {},
            seq=event.seq,
            recv_ns=event.recv_ns,
            session_hint=state.current_session or "",
        )

        # // [LAW:single-enforcer] Pending headers live on the Request record.
        req = context["request_registry"].get_or_create(event.request_id)
        pending_headers = req.pending_headers
        req.pending_headers = None  # consumed

        provider = event.provider
        blocks = cc_dump.core.formatting.format_request_for_provider(
            provider, body, state, request_headers=pending_headers
        )

        domain_store = context["domain_store"]
        turn_index = domain_store.add_turn(blocks)

        # // [LAW:one-source-of-truth] Provisional request state lives on Request,
        # consumed in _handle_complete_response_payload.
        req.turn_index = turn_index
        req.body = body
        req.provider = provider

        _refresh_stats_snapshot(context)

        log_fn("DEBUG", f"Request #{state.request_counter} processed")
    except Exception as e:
        log_fn("ERROR", f"Error handling request: {e}")
        raise


def handle_response_headers(event: ResponseHeadersEvent, state, context, log_fn) -> None:
    """Handle response_headers event."""
    status_code = event.status_code
    headers_dict = event.headers

    try:
        stream_registry = context["stream_registry"]
        req = context["request_registry"].get_or_create(event.request_id)
        req.response_status = status_code
        req.response_headers = _ensure_dict(headers_dict)
        stream_registry.mark_streaming(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )

        blocks = cc_dump.core.formatting.format_response_headers(status_code, headers_dict)

        domain_store = context["domain_store"]

        domain_store.begin_stream(event.request_id)

        for block in blocks:
            domain_store.append_stream_block(event.request_id, block)

        if blocks:
            log_fn(
                "DEBUG",
                f"Displayed response headers: HTTP {status_code}, {len(headers_dict)} headers",
            )
    except Exception as e:
        log_fn("ERROR", f"Error handling response headers: {e}")
        raise


def _upsert_current_turn_usage(req, progress: ResponseProgressEvent) -> None:
    """Merge progress usage/model data into Request.current_turn_usage."""
    current_turn = req.current_turn_usage if isinstance(req.current_turn_usage, dict) else {}

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

    req.current_turn_usage = current_turn


def handle_response_progress(event: ResponseProgressEvent, state, context, log_fn) -> None:
    """Handle transport-normalized streaming progress hints."""
    try:
        stream_registry = context["stream_registry"]
        stream_registry.mark_streaming(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )

        domain_store = context["domain_store"]
        domain_store.begin_stream(event.request_id)

        if event.delta_text:
            block = cc_dump.core.formatting.TextDeltaBlock(
                content=event.delta_text,
                category=cc_dump.core.formatting.Category.ASSISTANT,
            )
            domain_store.append_stream_block(event.request_id, block)

        req = context["request_registry"].get_or_create(event.request_id)
        _upsert_current_turn_usage(req, event)
        _refresh_stats_snapshot_throttled(context)
    except Exception as e:
        log_fn("ERROR", f"Error handling response progress: {e}")
        raise


def handle_response_event(event: ResponseSSEEvent, state, context, log_fn) -> None:
    """Compatibility shim for legacy SSE events.

    // [LAW:locality-or-seam] Legacy SSE transport is translated at this seam
    // into ResponseProgressEvent so downstream handlers stay transport-agnostic.
    """
    payload = sse_progress_payload(event.sse_event)
    if payload is None:
        return
    progress = ResponseProgressEvent(
        request_id=event.request_id,
        seq=event.seq,
        recv_ns=event.recv_ns,
        **payload,
    )
    handle_response_progress(progress, state, context, log_fn)


def handle_response_done(event: ResponseDoneEvent, state, context, log_fn) -> None:
    """Handle response_done event."""
    try:
        stream_registry = context["stream_registry"]
        stream_registry.mark_done(
            event.request_id,
            seq=event.seq,
            recv_ns=event.recv_ns,
        )
        domain_store = context["domain_store"]
        request_registry = context["request_registry"]

        # [LAW:single-enforcer] RESPONSE_COMPLETE is canonical finalization path.
        # RESPONSE_DONE only handles rare fallback where complete payload never arrived.
        if domain_store.get_stream_blocks(event.request_id):
            request_registry.pop(event.request_id)
            domain_store.finalize_stream(event.request_id)
            _refresh_post_response(state, context, rerender_budget=True)
            log_fn("DEBUG", "Response done fallback finalized active stream")
            return

        request_registry.pop(event.request_id)
        _refresh_stats_snapshot(context)
        log_fn("DEBUG", "Response done acknowledged")
    except Exception as e:
        log_fn("ERROR", f"Error handling response done: {e}")
        raise


def handle_error(event: ErrorEvent, state, context, log_fn) -> None:
    """Handle an error event."""
    code, reason = event.code, event.reason

    log_fn("ERROR", f"HTTP Error {code}: {reason}")

    block = cc_dump.core.formatting.ErrorBlock(code=code, reason=reason)

    domain_store = context["domain_store"]

    domain_store.add_turn([block])


def handle_proxy_error(event: ProxyErrorEvent, state, context, log_fn) -> None:
    """Handle a proxy_error event."""
    err = event.error

    log_fn("ERROR", f"Proxy error: {err}")

    block = cc_dump.core.formatting.ProxyErrorBlock(error=err)

    domain_store = context["domain_store"]

    domain_store.add_turn([block])


def handle_log(event: LogEvent, state, context, log_fn) -> None:
    """Handle a log event."""
    log_fn("DEBUG", f"HTTP {event.method} {event.path} -> {event.status}")


def handle_response_non_streaming(event: ResponseNonStreamingEvent, state, context, log_fn) -> None:
    """Normalize non-streaming transport into canonical complete-response path."""
    try:
        req = context["request_registry"].get_or_create(event.request_id)
        req.response_status = event.status_code
        req.response_headers = _ensure_dict(event.headers)
        _handle_complete_response_payload(
            request_id=event.request_id,
            complete_body=event.body,
            state=state,
            context=context,
            seq=event.seq,
            recv_ns=event.recv_ns,
            provider=event.provider,
        )
        log_fn("DEBUG", f"Complete response via non-streaming transport: HTTP {event.status_code}")
    except Exception as e:
        log_fn("ERROR", f"Error handling complete response: {e}")
        raise


def handle_response_complete(event: ResponseCompleteEvent, state, context, log_fn) -> None:
    """Handle reconstructed complete response event as the canonical UI path."""
    _handle_complete_response_payload(
        request_id=event.request_id,
        complete_body=event.body,
        state=state,
        context=context,
        seq=event.seq,
        recv_ns=event.recv_ns,
        provider=event.provider,
    )
    log_fn("DEBUG", "Complete response finalized")


def _noop(event, state, context, log_fn) -> None:
    """No-op handler for events that need no action."""
    return None


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
