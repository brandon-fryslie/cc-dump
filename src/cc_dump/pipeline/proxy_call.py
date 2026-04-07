"""Single-enforcer planning + execution boundary for proxy calls.

This module is the answer to the shotgun-parser shape that `_proxy` had: a
function asking "are we observing this call?" and "what shape is the response?"
at every step that should already know the answer. Here we model the call's
lifecycle as data, so the proxy interior becomes a straight pipe.

// [LAW:single-enforcer] All request-shape decisions live in `plan_proxy_call`.
//   All upstream-execution decisions live in `execute_upstream`. The HTTP
//   handler in proxy.py never re-asks "should this emit events?", "is this
//   streaming?", or "did the pipeline intercept?" — those questions cannot
//   be asked because the type already encodes the answer.
//
// // [LAW:dataflow-not-control-flow] Variance lives in the variant of
//   `PlannedCall` and `UpstreamResult`, not in branches inside the proxy.
//   The same operations execute in the same order on every request; the
//   values carry the differences.
//
// // [LAW:one-source-of-truth] upstream_format -> translator/header-builder
//   dispatch tables live here, with explicit identity rows. No `.get(...)`
//   silent-default lookups elsewhere in the proxy.
//
// // [LAW:one-type-per-behavior] Origin-resolution failure and interceptor
//   short-circuit are both "this call refuses to contact upstream and brings
//   its own response + events". They are one variant: `RefusedCall`.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import truststore

import cc_dump.pipeline.copilot_translate
import cc_dump.pipeline.proxy_flow
import cc_dump.providers
from cc_dump.pipeline.event_types import (
    ErrorEvent,
    PipelineEvent,
    ProxyErrorEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseCompleteEvent,
    ResponseDoneEvent,
    ResponseHeadersEvent,
    ResponseProgressEvent,
    event_envelope,
    new_request_id,
    parse_sse_event,
    sse_progress_payload,
)
from cc_dump.pipeline.response_assembler import ResponseAssembler
from cc_dump.providers import ProviderSpec, UpstreamFormat

if TYPE_CHECKING:
    from cc_dump.pipeline.proxy import StreamSink

logger = logging.getLogger(__name__)


# ─── Header filtering (boundary helper) ──────────────────────────────────────
# Mirrors proxy._safe_headers / proxy._EXCLUDED_HEADERS so the planner is
# self-contained. Single source of truth: this set.

_EXCLUDED_HEADERS = frozenset(
    {
        "authorization",
        "x-api-key",
        "cookie",
        "set-cookie",
        "host",
        "content-length",
        "transfer-encoding",
    }
)


def safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Filter sensitive and noisy headers for event emission."""
    return {k: v for k, v in headers.items() if k.lower() not in _EXCLUDED_HEADERS}


# ─── Request pipeline (transforms + interceptors) ────────────────────────────
# Moved here from proxy.py so the planner owns its own dependencies. The
# default value is an empty pipeline (identity), so the planner never has to
# ask `if request_pipeline is not None`.


@dataclass
class RequestPipeline:
    """Composable request processing: transforms modify, interceptors short-circuit.

    Phase 1 — transforms run unconditionally, each sees the output of the previous.
    Phase 2 — interceptors run after transforms. First non-None return wins.

    // [LAW:dataflow-not-control-flow] Empty pipeline = identity. There is no
    //   "no pipeline" mode flag; the absence of work is encoded as empty lists.
    """

    transforms: list[Callable[[dict, str], tuple[dict, str]]] = field(default_factory=list)
    interceptors: list[Callable[[dict], str | None]] = field(default_factory=list)

    def process(self, body: dict, url: str) -> tuple[dict, str, str | None]:
        """Run pipeline. Returns (body, url, intercept_response_or_none)."""
        for transform in self.transforms:
            body, url = transform(body, url)
        for interceptor in self.interceptors:
            response = interceptor(body)
            if response is not None:
                return body, url, response
        return body, url, None


# ─── Per-format dispatch tables ──────────────────────────────────────────────
# // [LAW:dataflow-not-control-flow] Each upstream_format has exactly one row.
# // [LAW:one-type-per-behavior] Identity translation is a function, not a
# //   missing key. The proxy never branches on `if translator is None`.


def _identity_translate_request(body: dict, url: str) -> tuple[dict, str]:
    return body, url


def _openai_responses_translate_request(body: dict, url: str) -> tuple[dict, str]:
    translated = cc_dump.pipeline.copilot_translate.anthropic_to_copilot_request(body)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    upstream_url = cc_dump.pipeline.copilot_translate.copilot_upstream_url(
        f"{parsed.scheme}://{parsed.netloc}"
    )
    return translated, upstream_url


def _openai_chat_translate_request(body: dict, url: str) -> tuple[dict, str]:
    translated = cc_dump.pipeline.copilot_translate.anthropic_to_chat_completions_request(body)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    upstream_url = cc_dump.pipeline.copilot_translate.copilot_chat_completions_url(
        f"{parsed.scheme}://{parsed.netloc}"
    )
    return translated, upstream_url


REQUEST_TRANSLATORS: dict[UpstreamFormat, Callable[[dict, str], tuple[dict, str]]] = {
    "anthropic": _identity_translate_request,
    "openai-responses": _openai_responses_translate_request,
    "openai-chat": _openai_chat_translate_request,
}


def _passthrough_headers(
    raw_headers: Mapping[str, str], body_bytes: bytes
) -> dict[str, str]:
    return cc_dump.pipeline.proxy_flow.build_upstream_headers(
        raw_headers, content_length=len(body_bytes),
    )


def _openai_responses_headers(
    raw_headers: Mapping[str, str], body_bytes: bytes
) -> dict[str, str]:
    token = cc_dump.pipeline.copilot_translate.read_copilot_token()
    return cc_dump.pipeline.copilot_translate.copilot_upstream_headers(
        {}, token, len(body_bytes),
    )


def _openai_chat_headers(
    raw_headers: Mapping[str, str], body_bytes: bytes
) -> dict[str, str]:
    token = cc_dump.pipeline.copilot_translate.read_copilot_token()
    messages: list = []
    try:
        body = json.loads(body_bytes)
        messages = body.get("messages", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return cc_dump.pipeline.copilot_translate.copilot_chat_headers(
        messages, token, len(body_bytes),
    )


HeaderBuilder = Callable[[Mapping[str, str], bytes], dict[str, str]]

HEADER_BUILDERS: dict[UpstreamFormat, HeaderBuilder] = {
    "anthropic": _passthrough_headers,
    "openai-responses": _openai_responses_headers,
    "openai-chat": _openai_chat_headers,
}


# ─── UpstreamResult: typed outcome of execute_upstream ───────────────────────
# // [LAW:dataflow-not-control-flow] HTTP outcome is a sum type, not a tuple
# //   of (resp, exception, is_streaming). Construction is the try/except;
# //   downstream code dispatches once over the variants and each arm is
# //   unconditional.


@dataclass(frozen=True)
class StreamingUpstream:
    """An open SSE response. body_source is a live iterable of bytes."""
    status: int
    headers: Mapping[str, str]            # raw upstream headers, forwarded as-is
    body_source: Iterable[bytes]          # live response object


@dataclass(frozen=True)
class UnaryUpstream:
    """A non-streaming successful response, body fully read."""
    status: int
    headers: Mapping[str, str]
    body_bytes: bytes


@dataclass(frozen=True)
class HttpErrorUpstream:
    """An HTTP error response (non-2xx), body fully read."""
    status: int
    headers: Mapping[str, str]
    body_bytes: bytes


@dataclass(frozen=True)
class NetworkErrorUpstream:
    """Connection-level failure — no upstream response was received."""
    error: str


UpstreamResult = (
    StreamingUpstream | UnaryUpstream | HttpErrorUpstream | NetworkErrorUpstream
)


# ─── ResponseEventEmitter capability ─────────────────────────────────────────
# This is the mechanism that absorbs the `emitted_request` mode flag. A
# TracedCall carries a real emitter that builds events from upstream results.
# A ForwardOnlyCall carries the null base, whose every method returns nothing.
# The proxy interior calls the methods unconditionally and the null variant
# is a no-op — same operations every call, dataflow not control flow.


class ResponseEventEmitter:
    """Null emitter — every method returns no events / no sinks.

    ForwardOnlyCall uses this directly. The proxy interior treats it like
    any other emitter, calling its methods unconditionally; the absence of
    events is data, not a branch.
    """

    def emit_unary(
        self, upstream: UnaryUpstream
    ) -> tuple[PipelineEvent, ...]:
        return ()

    def emit_http_error(
        self, upstream: HttpErrorUpstream
    ) -> tuple[PipelineEvent, ...]:
        return ()

    def emit_network_error(
        self, upstream: NetworkErrorUpstream
    ) -> tuple[PipelineEvent, ...]:
        return ()

    def emit_streaming_headers(
        self, upstream: StreamingUpstream
    ) -> tuple[PipelineEvent, ...]:
        return ()

    def streaming_extra_sinks(self, event_queue) -> list["StreamSink"]:
        return []

    def streaming_finalize(
        self, sinks: list["StreamSink"]
    ) -> tuple[PipelineEvent, ...]:
        return ()


class TracedResponseEventEmitter(ResponseEventEmitter):
    """Real emitter for observed API calls. Builds the full event sequence
    that the TUI / HAR recorder / analytics expect.

    // [LAW:single-enforcer] Response-side event construction lives here only.
    """

    def __init__(self, *, request_id: str, provider: str) -> None:
        self._request_id = request_id
        self._provider = provider

    def _envelope(self, seq: int) -> dict:
        return event_envelope(
            request_id=self._request_id,
            seq=seq,
            provider=self._provider,
        )

    def emit_unary(
        self, upstream: UnaryUpstream
    ) -> tuple[PipelineEvent, ...]:
        body = cc_dump.pipeline.proxy_flow.decode_json_response_body(upstream.body_bytes)
        return (
            ResponseHeadersEvent(
                status_code=upstream.status,
                headers=safe_headers(upstream.headers),
                **self._envelope(0),
            ),
            ResponseCompleteEvent(
                body=body,
                **self._envelope(1),
            ),
        )

    def emit_http_error(
        self, upstream: HttpErrorUpstream
    ) -> tuple[PipelineEvent, ...]:
        body = cc_dump.pipeline.proxy_flow.decode_json_response_body(upstream.body_bytes)
        # // [LAW:one-type-per-behavior] Error responses ARE responses — emit
        # //   the same event shape as success so HAR / analytics see them.
        return (
            ErrorEvent(
                code=upstream.status,
                reason=_status_reason(upstream),
                **self._envelope(0),
            ),
            ResponseHeadersEvent(
                status_code=upstream.status,
                headers=safe_headers(upstream.headers),
                **self._envelope(1),
            ),
            ResponseCompleteEvent(
                body=body,
                **self._envelope(2),
            ),
        )

    def emit_network_error(
        self, upstream: NetworkErrorUpstream
    ) -> tuple[PipelineEvent, ...]:
        return (
            ProxyErrorEvent(
                error=upstream.error,
                **self._envelope(0),
            ),
        )

    def emit_streaming_headers(
        self, upstream: StreamingUpstream
    ) -> tuple[PipelineEvent, ...]:
        return (
            ResponseHeadersEvent(
                status_code=upstream.status,
                headers=safe_headers(upstream.headers),
                **self._envelope(0),
            ),
        )

    def streaming_extra_sinks(self, event_queue) -> list["StreamSink"]:
        # Imported lazily to avoid a circular import with proxy.py.
        from cc_dump.pipeline.proxy import EventQueueSink
        from cc_dump.pipeline.response_assembler import OpenAiChatResponseAssembler

        family = cc_dump.providers.get_provider_spec(self._provider).protocol_family
        assembler_cls = (
            ResponseAssembler if family == "anthropic" else OpenAiChatResponseAssembler
        )
        # The streaming headers event uses seq=0 of the response side. The
        # EventQueueSink starts at seq_start=1 so the first ResponseProgress
        # event is seq=1, leaving room for the headers event at seq=0.
        return [
            EventQueueSink(
                event_queue,
                request_id=self._request_id,
                seq_start=1,
                provider=self._provider,
            ),
            assembler_cls(),
        ]

    def streaming_finalize(
        self, sinks: list["StreamSink"]
    ) -> tuple[PipelineEvent, ...]:
        from cc_dump.pipeline.proxy import EventQueueSink

        # Recover the assembler + event sink from the list. Their order is
        # fixed by streaming_extra_sinks above. We do not branch on which
        # is which — we know structurally.
        event_sink: EventQueueSink = sinks[0]  # type: ignore[assignment]
        assembler = sinks[1]
        seq = event_sink.seq
        events: list[PipelineEvent] = []
        result = getattr(assembler, "result", None)
        if result is not None:
            seq += 1
            events.append(
                ResponseCompleteEvent(body=result, **self._envelope(seq))
            )
        seq += 1
        events.append(ResponseDoneEvent(**self._envelope(seq)))
        return tuple(events)


def _status_reason(upstream: HttpErrorUpstream) -> str:
    # urllib.error.HTTPError has .reason; we lost the object on the way in,
    # so reconstruct a human label from the status code via http.client.
    import http.client
    return http.client.responses.get(upstream.status, "")


# ─── PlannedCall: typed outcome of plan_proxy_call ───────────────────────────


@dataclass(frozen=True, kw_only=True)
class TracedCall:
    """API request that will be observed. The presence of `request_events`
    and the real `emitter` is what distinguishes this from ForwardOnlyCall."""
    provider: str
    spec: ProviderSpec
    method: str
    upstream_url: str
    upstream_headers: dict[str, str]
    upstream_body_bytes: bytes
    request_id: str
    parsed_body: dict[str, object]
    request_events: tuple[PipelineEvent, ...]
    emitter: ResponseEventEmitter


@dataclass(frozen=True, kw_only=True)
class ForwardOnlyCall:
    """Non-API traffic. Forwarded but produces no pipeline events.

    Carries an empty `request_events` and a null `emitter` so the proxy
    interior treats it identically to TracedCall — same calls, no events.
    """
    provider: str
    spec: ProviderSpec
    method: str
    upstream_url: str
    upstream_headers: dict[str, str]
    upstream_body_bytes: bytes
    request_events: tuple[PipelineEvent, ...] = ()
    emitter: ResponseEventEmitter = field(default_factory=ResponseEventEmitter)


@dataclass(frozen=True, kw_only=True)
class RefusedCall:
    """The call will not contact upstream. Brings its own response + events.

    Covers two cases that share this exact shape:
      1. Origin resolution failed (no valid target).
      2. Interceptor short-circuited (synthetic response).
    """
    status: int
    response_headers: dict[str, str]
    response_body_bytes: bytes
    events: tuple[PipelineEvent, ...]


PlannedCall = TracedCall | ForwardOnlyCall | RefusedCall

# Convenience union for "calls that contact upstream".
OutboundCall = TracedCall | ForwardOnlyCall


# ─── plan_proxy_call: SINGLE ENFORCER for request-side decisions ─────────────


def plan_proxy_call(
    *,
    method: str,
    path: str,
    raw_headers: Mapping[str, str],
    body_bytes: bytes,
    provider: str,
    target_host: str | None,
    required_origin: str | None,
    request_pipeline: RequestPipeline,
) -> PlannedCall:
    """Resolve everything about an incoming proxy request into typed data.

    The return value is a complete description of what to do next:
      * RefusedCall — write its bytes to the client, emit its events.
      * ForwardOnlyCall — contact upstream, forward bytes, emit nothing.
      * TracedCall — emit request events, contact upstream, forward bytes,
                     emit response events via the emitter.

    No code outside this function decides "is this an API call?",
    "should we translate?", "did the pipeline intercept?", or "is the
    request_pipeline configured?". Those questions are answered here, once.
    """
    spec = cc_dump.providers.get_provider_spec(provider)

    # Step 1: resolve upstream URL (or refuse).
    target = cc_dump.pipeline.proxy_flow.resolve_proxy_target_for_origin(
        path,
        target_host,
        required_origin=required_origin,
    )
    if target.error_reason:
        request_id = new_request_id()
        return RefusedCall(
            status=target.error_status or 500,
            response_headers={},
            response_body_bytes=b"No target configured. Use --target or send absolute URIs.",
            events=(
                ErrorEvent(
                    code=target.error_status or 500,
                    reason=target.error_reason,
                    **event_envelope(
                        request_id=request_id, seq=0, provider=provider,
                    ),
                ),
            ),
        )

    # Step 2: parse request body. Empty / non-API / malformed all collapse
    # to "no parsed body" which means ForwardOnlyCall below.
    expects_json = any(target.request_path.startswith(p) for p in spec.api_paths)
    parsed_body, parse_error = cc_dump.pipeline.proxy_flow.parse_request_json(
        body_bytes, expects_json=expects_json,
    )
    if parse_error:
        logger.warning("malformed request JSON: %s", parse_error)

    if parsed_body is None:
        # ForwardOnlyCall path: no translation, no pipeline, no events.
        # Headers go through the passthrough builder for the ProviderSpec's
        # default identity case.
        upstream_headers = _passthrough_headers(raw_headers, body_bytes)
        return ForwardOnlyCall(
            provider=provider,
            spec=spec,
            method=method,
            upstream_url=target.upstream_url,
            upstream_headers=upstream_headers,
            upstream_body_bytes=body_bytes,
        )

    # Step 3: TracedCall path. Translate, run pipeline, build headers.
    request_id = new_request_id()
    safe_req_headers = safe_headers(raw_headers)

    # Translate request body+URL by upstream_format.
    translator = REQUEST_TRANSLATORS[spec.upstream_format]
    translated_body, translated_url = translator(parsed_body, target.upstream_url)

    # Run the request pipeline (default = empty = identity).
    final_body, final_url, intercept_response = request_pipeline.process(
        translated_body, translated_url,
    )
    upstream_body_bytes = json.dumps(final_body).encode()

    # Pre-build the request-side events that every TracedCall emits.
    request_events: tuple[PipelineEvent, ...] = (
        # // [LAW:one-source-of-truth] request_id/seq envelope is on request
        # //   events too, not only response events.
        RequestHeadersEvent(
            headers=safe_req_headers,
            **event_envelope(request_id=request_id, seq=0, provider=provider),
        ),
        RequestBodyEvent(
            body=final_body,
            **event_envelope(request_id=request_id, seq=1, provider=provider),
        ),
    )

    # If the interceptor short-circuited, this becomes a RefusedCall that
    # carries the request events AND the synthesized response events. From
    # the proxy's perspective: same RefusedCall variant as origin failure,
    # just with more events.
    if intercept_response is not None:
        return _build_synthetic_refused(
            response_text=intercept_response,
            request_body=final_body,
            request_id=request_id,
            provider=provider,
            request_events=request_events,
        )

    # Build upstream headers using the format-keyed dispatch.
    header_builder = HEADER_BUILDERS[spec.upstream_format]
    upstream_headers = header_builder(raw_headers, upstream_body_bytes)

    return TracedCall(
        provider=provider,
        spec=spec,
        method=method,
        upstream_url=final_url,
        upstream_headers=upstream_headers,
        upstream_body_bytes=upstream_body_bytes,
        request_id=request_id,
        parsed_body=final_body,
        request_events=request_events,
        emitter=TracedResponseEventEmitter(
            request_id=request_id, provider=provider,
        ),
    )


def _build_synthetic_refused(
    *,
    response_text: str,
    request_body: dict,
    request_id: str,
    provider: str,
    request_events: tuple[PipelineEvent, ...],
) -> RefusedCall:
    """Build a RefusedCall that carries a synthetic SSE response + its events.

    // [LAW:single-enforcer] Synthetic-response construction lives here only.
    //   What used to be _send_synthetic_response is now data: a list of
    //   events plus the bytes to write to the client.
    """
    # Late import to avoid module-load cycle with proxy.py.
    from cc_dump.pipeline.proxy import _build_synthetic_sse_bytes

    model_value = request_body.get("model", "synthetic")
    model = model_value if isinstance(model_value, str) else "synthetic"

    sse_bytes = _build_synthetic_sse_bytes(response_text, model)

    # Replay the synthetic SSE through an assembler so we can produce the
    # same Progress + Complete events the live path produces. This is the
    # same logic the old _send_synthetic_response had inline; it lives here
    # now and produces a tuple of events instead of pushing them to a queue.
    assembler = ResponseAssembler()
    events: list[PipelineEvent] = list(request_events)

    seq = 0
    events.append(
        ResponseHeadersEvent(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            **event_envelope(request_id=request_id, seq=seq, provider=provider),
        )
    )

    for line in sse_bytes.split(b"\n"):
        line_str = line.decode("utf-8", errors="replace").rstrip("\r")
        if not line_str.startswith("data: "):
            continue
        json_str = line_str[6:]
        if json_str == "[DONE]":
            break
        try:
            event = json.loads(json_str)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type", "")
        assembler.on_event(event_type, event)
        try:
            sse = parse_sse_event(event_type, event)
        except ValueError:
            continue
        payload = sse_progress_payload(sse)
        if payload is None:
            continue
        seq += 1
        events.append(
            ResponseProgressEvent(
                **event_envelope(request_id=request_id, seq=seq, provider=provider),
                **payload,
            )
        )

    assembler.on_done()
    if assembler.result is not None:
        seq += 1
        events.append(
            ResponseCompleteEvent(
                body=assembler.result,
                **event_envelope(request_id=request_id, seq=seq, provider=provider),
            )
        )
    seq += 1
    events.append(
        ResponseDoneEvent(
            **event_envelope(request_id=request_id, seq=seq, provider=provider),
        )
    )

    return RefusedCall(
        status=200,
        response_headers={"Content-Type": "text/event-stream"},
        response_body_bytes=sse_bytes,
        events=tuple(events),
    )


# ─── execute_upstream: SINGLE ENFORCER for HTTP outcome ──────────────────────


def execute_upstream(call: OutboundCall) -> UpstreamResult:
    """Contact upstream and return a typed outcome.

    The try/except lives here. Streaming detection lives here. Caller code
    receives a sum type and dispatches once over the variants — it never
    asks `is_stream` or wraps another try/except.

    // [LAW:single-enforcer] HTTP transport for the proxy lives here.
    """
    req = urllib.request.Request(
        call.upstream_url,
        data=call.upstream_body_bytes or None,
        headers=call.upstream_headers,
        method=call.method,
    )
    try:
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        resp = urllib.request.urlopen(req, context=ctx, timeout=300)
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        return HttpErrorUpstream(
            status=e.code,
            headers=e.headers,
            body_bytes=body_bytes,
        )
    except Exception as e:
        return NetworkErrorUpstream(error=str(e))

    # Streaming vs unary is decided by Content-Type. The check lives here,
    # exactly once, and is reified as the variant of UpstreamResult.
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        return StreamingUpstream(
            status=resp.status,
            headers=resp.headers,
            body_source=resp,
        )
    return UnaryUpstream(
        status=resp.status,
        headers=resp.headers,
        body_bytes=resp.read(),
    )
