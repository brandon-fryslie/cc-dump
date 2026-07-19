"""HTTP proxy handler — pure data source, no display logic.

// [LAW:single-enforcer] All planning and HTTP-transport decisions live in
//   pipeline/proxy_call.py. This module is the BaseHTTPRequestHandler glue
//   that drives the planner and writes its outputs to the wire.
"""

import http.server
import json
import logging
import queue
import ssl
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from cc_dump.pipeline.event_types import (
    LogEvent,
    PipelineEvent,
    ResponseCompleteEvent,
    ResponseDoneEvent,
    ResponseProgressEvent,
    event_envelope,
    parse_sse_event,
    sse_progress_payload,
)
from cc_dump.pipeline.proxy_call import (
    HttpErrorUpstream,
    NetworkErrorUpstream,
    OutboundCall,
    PlannedCall,
    RefusedCall,
    RequestPipeline,
    StreamingUpstream,
    UnaryUpstream,
    UpstreamResult,
    execute_upstream,
    plan_proxy_call,
)
from cc_dump.pipeline.response_assembler import ResponseAssembler
import cc_dump.pipeline.proxy_flow
import cc_dump.providers

# Re-export RequestPipeline so existing imports (`from cc_dump.pipeline.proxy
# import RequestPipeline` in cli.py) keep working.
__all__ = ["ProxyHandler", "RequestPipeline", "make_handler_class"]

if TYPE_CHECKING:
    from cc_dump.pipeline.forward_proxy_tls import ForwardProxyCertificateAuthority

# Headers to exclude from emitted events (security + noise reduction)
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
logger = logging.getLogger(__name__)


def _safe_headers(headers):
    """Filter out sensitive and noisy headers."""
    return {k: v for k, v in headers.items() if k.lower() not in _EXCLUDED_HEADERS}


def _parse_connect_authority(authority: str) -> tuple[str, int] | None:
    """Parse CONNECT authority into (host, port).

    Accepts:
    - host
    - host:port
    - [ipv6]
    - [ipv6]:port
    Returns None for malformed values.
    """
    value = str(authority or "").strip()
    if not value:
        return None

    host = ""
    port = 443

    if value.startswith("["):
        end = value.find("]")
        if end <= 1:
            return None
        host = value[1:end]
        suffix = value[end + 1:]
        if not suffix:
            port = 443
        elif suffix.startswith(":"):
            port_text = suffix[1:]
            if not port_text.isdigit():
                return None
            port = int(port_text)
        else:
            return None
    else:
        if ":" in value:
            if value.count(":") != 1:
                return None
            host, port_text = value.rsplit(":", 1)
            if not port_text.isdigit():
                return None
            port = int(port_text)
        else:
            host = value
            port = 443

    if not host or port < 1 or port > 65535:
        return None
    return host, port


# RequestPipeline lives in pipeline/proxy_call.py — re-exported above for
# back-compat with `from cc_dump.pipeline.proxy import RequestPipeline`.


def _build_synthetic_sse_bytes(response_text: str, model: str = "synthetic") -> bytes:
    """Build complete SSE byte stream for a synthetic response.

    // [LAW:dataflow-not-control-flow] Pure function — data in, bytes out.
    """
    msg_id = "msg_synthetic_" + uuid.uuid4().hex[:12]
    chunks = []

    # message_start
    chunks.append(
        _sse_line(
            {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }
        )
    )

    # content_block_start
    chunks.append(
        _sse_line(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }
        )
    )

    # content_block_delta (full text in one delta)
    chunks.append(
        _sse_line(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": response_text},
            }
        )
    )

    # content_block_stop
    chunks.append(_sse_line({"type": "content_block_stop", "index": 0}))

    # message_delta
    chunks.append(
        _sse_line(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            }
        )
    )

    # message_stop
    chunks.append(_sse_line({"type": "message_stop"}))

    # [DONE]
    chunks.append(b"data: [DONE]\n\n")

    return b"".join(chunks)


def _sse_line(event: dict) -> bytes:
    """Format a single SSE data line."""
    return b"data: " + json.dumps(event).encode() + b"\n\n"


def _iter_chat_sse_chunks(resp):
    """Parse an SSE byte stream into decoded JSON chunks.

    // [LAW:single-enforcer] One place owns SSE line buffering + JSON decode.
    //   Callers receive already-decoded dicts and never branch on framing.
    """
    buf = b""
    for raw in resp:
        buf += raw
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").strip()
            if not text.startswith("data: "):
                continue
            data_str = text[6:]
            if data_str == "[DONE]":
                continue
            try:
                yield json.loads(data_str)
            except json.JSONDecodeError:
                continue


def _call_sink(fn, label: str) -> None:
    """Run a sink callable inside a logged error boundary.

    // [LAW:single-enforcer] Error isolation shape lives here, not scattered
    //   as try/except pellets at each sink callsite.
    """
    try:
        fn()
    except Exception as exc:
        logger.warning("%s: %s", label, exc)


class StreamSink:
    """Consumer of an SSE stream. Each method is called in its own error boundary."""

    def on_raw(self, data: bytes) -> None:
        pass

    def on_event(self, event_type: str, event: dict) -> None:
        pass

    def on_done(self) -> None:
        pass


class ClientSink(StreamSink):
    """Writes raw SSE bytes back to the HTTP client."""

    def __init__(self, wfile):
        self._wfile = wfile

    def on_raw(self, data):
        self._wfile.write(data)
        self._wfile.flush()


class EventQueueSink(StreamSink):
    """Emits parsed events to the TUI event queue."""

    def __init__(self, queue, request_id: str = "", seq_start: int = 0, provider: str = "anthropic"):
        self._queue = queue
        self._request_id = request_id
        self._seq = seq_start
        self._provider = provider

    def on_event(self, event_type, event):
        # [LAW:dataflow-not-control-flow] Provider family selects extraction strategy.
        family = cc_dump.providers.get_provider_spec(self._provider).protocol_family
        extract = _PROGRESS_EXTRACTORS_BY_FAMILY.get(family, _extract_openai_chat_progress)
        payload = extract(event_type, event)
        if payload is None:
            return
        self._seq += 1
        self._queue.put(
            ResponseProgressEvent(
                **event_envelope(
                    request_id=self._request_id,
                    seq=self._seq,
                    provider=self._provider,
                ),
                **payload,
            )
        )

    def on_done(self):
        pass  # [LAW:single-enforcer] proxy emits ResponseDoneEvent explicitly

    @property
    def seq(self) -> int:
        return self._seq


def _extract_anthropic_progress(event_type: str, event: dict) -> dict[str, object] | None:
    """Extract progress payload from Anthropic SSE event."""
    try:
        sse = parse_sse_event(event_type, event)
    except ValueError:
        return None
    return sse_progress_payload(sse)


def _openai_chat_model_payload(event: dict) -> dict[str, object] | None:
    model = event.get("model")
    return {"model": model} if isinstance(model, str) and model else None


def _openai_chat_first_choice(event: dict) -> dict | None:
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    return first_choice if isinstance(first_choice, dict) else None


def _openai_chat_delta_text_payload(choice: dict) -> dict[str, object] | None:
    delta = choice.get("delta", {})
    if not isinstance(delta, dict):
        return None
    content = delta.get("content")
    return {"delta_text": content} if isinstance(content, str) and content else None


def _openai_chat_finish_reason_payload(choice: dict) -> dict[str, object] | None:
    finish_reason = choice.get("finish_reason")
    return (
        {"stop_reason": finish_reason}
        if isinstance(finish_reason, str) and finish_reason
        else None
    )


def _extract_openai_chat_progress(_event_type: str, event: dict) -> dict[str, object] | None:
    """Extract progress payload from OpenAI SSE event (stub).

    OpenAI SSE format: {"id":"...","choices":[{"index":0,"delta":{"content":"..."}}]}
    """
    choice = _openai_chat_first_choice(event)
    candidate_payloads = (
        _openai_chat_delta_text_payload(choice or {}),
        _openai_chat_finish_reason_payload(choice or {}),
        _openai_chat_model_payload(event),
    )
    return next((payload for payload in candidate_payloads if payload is not None), None)


# [LAW:dataflow-not-control-flow] Protocol family → progress extraction strategy.
_PROGRESS_EXTRACTORS_BY_FAMILY: dict[str, Callable[[str, dict], dict[str, object] | None]] = {
    "anthropic": _extract_anthropic_progress,
    "openai": _extract_openai_chat_progress,
}


def _fan_out_sse(resp, sinks):
    """Drive an SSE response to multiple sinks with per-sink error isolation."""
    def _safe_sink_call(phase: str, sink, method_name: str, *args: object) -> None:
        try:
            getattr(sink, method_name)(*args)
        except Exception as exc:
            # [LAW:single-enforcer] Sink failure handling is centralized and explicit.
            logger.warning(
                "SSE sink failure during %s (%s): %s",
                phase,
                sink.__class__.__name__,
                exc,
            )

    # [LAW:dataflow-not-control-flow] All sinks called unconditionally
    try:
        for raw_line in resp:
            for sink in sinks:
                _safe_sink_call("on_raw", sink, "on_raw", raw_line)

            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            json_str = line[6:]
            if json_str == "[DONE]":
                break

            try:
                event = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")
            for sink in sinks:
                _safe_sink_call("on_event", sink, "on_event", event_type, event)
    finally:
        for sink in sinks:
            _safe_sink_call("on_done", sink, "on_done")


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    target_host: str | None = None  # set by cli.py or factory before server starts
    event_queue: queue.Queue[PipelineEvent] = queue.Queue()  # set by cli.py or factory before server starts
    # // [LAW:dataflow-not-control-flow] Default is the empty (identity)
    # //   pipeline, NOT None. The proxy never asks "if request_pipeline is
    # //   not None"; the absence of work is encoded as empty lists.
    request_pipeline: RequestPipeline = RequestPipeline()
    provider: str = "anthropic"  # set by factory for multi-provider support
    forward_proxy_ca: "ForwardProxyCertificateAuthority | None" = None  # set by factory when forward proxy CONNECT interception is enabled

    def log_message(self, fmt, *args):
        self.event_queue.put(LogEvent(method=self.command, path=self.path, status=args[0] if args else "", provider=self.provider))

    def _active_target_host(self) -> str | None:
        tunnel_target = getattr(self, "_connect_target_host", None)
        return tunnel_target if tunnel_target is not None else self.target_host

    def _proxy(self) -> None:
        """Drive the proxy_call planner and write its outputs to the wire.

        // [LAW:dataflow-not-control-flow] Same operations every request:
        //   plan → emit request events → execute → deliver. The variant of
        //   PlannedCall and UpstreamResult carries all variance.
        // // [LAW:single-enforcer] No request-shape decisions live here.
        //   Translation, interception, header building, JSON parsing,
        //   and HTTP transport all live in pipeline/proxy_call.py.
        """
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len else b""

        planned = plan_proxy_call(
            method=self.command,
            path=self.path,
            raw_headers=self.headers,
            body_bytes=body_bytes,
            provider=self.provider,
            target_host=self._active_target_host(),
            required_origin=getattr(self, "_connect_target_host", None),
            request_pipeline=self.request_pipeline,
        )
        self._dispatch(planned)

    def _dispatch(self, planned: PlannedCall) -> None:
        # // [LAW:dataflow-not-control-flow] One match over the call shape.
        # //   RefusedCall is short-circuit; the outbound variants share the
        # //   exact same straight-pipe path because the emitter absorbs the
        # //   "is this observed?" decision.
        if isinstance(planned, RefusedCall):
            self._deliver_refused(planned)
            return

        self._emit_events(planned.request_events)
        upstream = execute_upstream(planned)
        self._deliver_upstream(planned, upstream)

    def _emit_events(self, events) -> None:
        for evt in events:
            self.event_queue.put(evt)

    def _deliver_refused(self, refused: RefusedCall) -> None:
        self.send_response(refused.status)
        for k, v in refused.response_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(refused.response_body_bytes)
        try:
            self.wfile.flush()
        except Exception:
            pass
        self._emit_events(refused.events)

    def _deliver_upstream(
        self, planned: OutboundCall, upstream: UpstreamResult
    ) -> None:
        # // [LAW:dataflow-not-control-flow] One match over the upstream shape.
        # //   Each arm calls planned.emitter.emit_*; for ForwardOnly the
        # //   null emitter returns no events and the loop emits nothing —
        # //   no `if emitted_request:` re-checks anywhere.
        match upstream:
            case StreamingUpstream():
                self._deliver_streaming(planned, upstream)
            case UnaryUpstream():
                self._write_response(upstream.status, upstream.headers, upstream.body_bytes)
                self._emit_events(planned.emitter.emit_unary(upstream))
            case HttpErrorUpstream():
                self._write_response(upstream.status, upstream.headers, upstream.body_bytes)
                self._emit_events(planned.emitter.emit_http_error(upstream))
            case NetworkErrorUpstream():
                self.send_response(502)
                self.end_headers()
                self._emit_events(planned.emitter.emit_network_error(upstream))

    def _write_response(self, status: int, headers, body_bytes: bytes) -> None:
        """Forward a non-streaming upstream response to the client."""
        self.send_response(status)
        for k, v in headers.items():
            if k.lower() == "transfer-encoding":
                continue
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body_bytes)

    def _deliver_streaming(
        self, planned: OutboundCall, upstream: StreamingUpstream
    ) -> None:
        # Forward HTTP status + headers (always — every variant of OutboundCall
        # is forwarding bytes to the client; the only difference is event emission).
        self.send_response(upstream.status)
        for k, v in upstream.headers.items():
            if k.lower() == "transfer-encoding":
                continue
            self.send_header(k, v)
        self.end_headers()

        # Response-headers event (empty tuple for ForwardOnly).
        self._emit_events(planned.emitter.emit_streaming_headers(upstream))

        # // [LAW:dataflow-not-control-flow] One load-bearing branch:
        # //   translated SSE protocols vs passthrough fan-out. The strategy
        # //   name lives on the emitter (None for ForwardOnly + anthropic),
        # //   so the proxy never asks "is this traced?" or "what format?".
        translation_handler = planned.emitter.translation_handler_name
        if translation_handler is not None:
            getattr(self, translation_handler)(
                upstream.body_source, planned.emitter.request_id,
            )
            return

        # Default fan-out: client + emitter-supplied sinks ([] for ForwardOnly).
        extra_sinks = planned.emitter.streaming_extra_sinks(self.event_queue)
        sinks: list = [ClientSink(self.wfile), *extra_sinks]
        _fan_out_sse(upstream.body_source, sinks)
        self._emit_events(planned.emitter.streaming_finalize(extra_sinks))

    def _stream_translated_response(self, resp, request_id: str = ""):
        """Stream Copilot (OpenAI Responses API) SSE, translating to Anthropic format.

        Reads Copilot SSE events from upstream, translates each to Anthropic SSE events,
        writes Anthropic-format bytes to client, and feeds Anthropic events to the
        TUI pipeline (EventQueueSink + ResponseAssembler).

        // [LAW:dataflow-not-control-flow] Same sink pipeline as _stream_response —
        // the translation happens before events enter the sinks.
        // [LAW:single-enforcer] Copilot→Anthropic SSE translation is here only.
        """
        parser = cc_dump.pipeline.copilot_translate.CopilotSSEParser()
        state = cc_dump.pipeline.copilot_translate.TranslationState()
        assembler = ResponseAssembler()
        event_sink = EventQueueSink(self.event_queue, request_id=request_id, provider=self.provider)

        try:
            for raw_line in resp:
                parsed_events = parser.feed(raw_line)
                for copilot_event_type, copilot_data in parsed_events:
                    anthropic_events = cc_dump.pipeline.copilot_translate.copilot_sse_to_anthropic_events(
                        copilot_event_type, copilot_data, state,
                    )
                    for anth_event in anthropic_events:
                        # Write Anthropic SSE bytes to client
                        anth_bytes = cc_dump.pipeline.copilot_translate.anthropic_sse_line(anth_event)
                        try:
                            self.wfile.write(anth_bytes)
                            self.wfile.flush()
                        except Exception as exc:
                            logger.warning("Client write failure: %s", exc)

                        # Feed to TUI pipeline sinks
                        anth_type = anth_event.get("type", "")
                        try:
                            event_sink.on_event(anth_type, anth_event)
                        except Exception as exc:
                            logger.warning("EventQueueSink failure: %s", exc)
                        try:
                            assembler.on_event(anth_type, anth_event)
                        except Exception as exc:
                            logger.warning("ResponseAssembler failure: %s", exc)
        finally:
            try:
                event_sink.on_done()
            except Exception:
                pass
            try:
                assembler.on_done()
            except Exception:
                pass

        seq = event_sink.seq
        if assembler.result is not None:
            seq += 1
            self.event_queue.put(ResponseCompleteEvent(
                body=assembler.result,
                **event_envelope(
                    request_id=request_id,
                    seq=seq,
                    provider=self.provider,
                ),
            ))
        seq += 1
        self.event_queue.put(ResponseDoneEvent(
            **event_envelope(
                request_id=request_id,
                seq=seq,
                provider=self.provider,
            ),
        ))

    def _emit_translated_event(self, anth_event: dict, event_sink, assembler) -> None:
        """Fan one Anthropic-shaped event to client + sinks with per-sink boundaries.

        // [LAW:dataflow-not-control-flow] Fan-out is a straight sequence, each
        //   sink call isolated by one `_call_sink` wrapper.
        """
        anth_bytes = cc_dump.pipeline.copilot_translate.anthropic_sse_line(anth_event)

        def _write_to_client() -> None:
            self.wfile.write(anth_bytes)
            self.wfile.flush()

        _call_sink(_write_to_client, "Client write failure")
        anth_type = anth_event.get("type", "")
        _call_sink(lambda: event_sink.on_event(anth_type, anth_event),
                   "EventQueueSink failure")
        _call_sink(lambda: assembler.on_event(anth_type, anth_event),
                   "ResponseAssembler failure")

    def _stream_chat_translated_response(self, resp, request_id: str = ""):
        """Stream Chat Completions SSE, translating to Anthropic format.

        // [LAW:single-enforcer] Chat Completions→Anthropic SSE translation is here only.
        """
        state = cc_dump.pipeline.copilot_translate.ChatTranslationState()
        assembler = ResponseAssembler()
        event_sink = EventQueueSink(self.event_queue, request_id=request_id, provider=self.provider)

        try:
            for chunk in _iter_chat_sse_chunks(resp):
                anthropic_events = cc_dump.pipeline.copilot_translate.chat_chunk_to_anthropic_events(
                    chunk, state,
                )
                for anth_event in anthropic_events:
                    self._emit_translated_event(anth_event, event_sink, assembler)
        finally:
            _call_sink(event_sink.on_done, "EventQueueSink.on_done failure")
            _call_sink(assembler.on_done, "ResponseAssembler.on_done failure")

        seq = event_sink.seq
        if assembler.result is not None:
            seq += 1
            self.event_queue.put(ResponseCompleteEvent(
                body=assembler.result,
                **event_envelope(
                    request_id=request_id,
                    seq=seq,
                    provider=self.provider,
                ),
            ))
        seq += 1
        self.event_queue.put(ResponseDoneEvent(
            **event_envelope(
                request_id=request_id,
                seq=seq,
                provider=self.provider,
            ),
        ))

    def do_CONNECT(self):
        """Handle HTTPS CONNECT tunneling with forward-proxy TLS interception."""
        parsed_authority = _parse_connect_authority(self.path)
        if parsed_authority is None:
            self.send_error(400, "Malformed CONNECT authority")
            return
        host, port = parsed_authority

        if not self.forward_proxy_ca:
            self.send_error(501, "CONNECT not supported in reverse proxy mode")
            return

        route = cc_dump.providers.resolve_forward_proxy_connect_route(
            self.provider,
            host=host,
            port=port,
        )
        if route is None:
            self.send_error(403, "CONNECT host not allowed for provider")
            return

        # Tell client the tunnel is established.
        self.send_response(200, "Connection Established")
        self.end_headers()

        # Wrap client socket in TLS with a cert generated for this host.
        ctx = self.forward_proxy_ca.ssl_context_for_host(host)
        try:
            client_ssl = ctx.wrap_socket(self.connection, server_side=True)
        except ssl.SSLError:
            logger.debug("Forward-proxy TLS handshake failed for %s", host)
            return

        # Replace streams with the decrypted socket.
        self.connection = client_ssl
        self.rfile = client_ssl.makefile("rb")
        self.wfile = client_ssl.makefile("wb")

        # Route decrypted HTTP through the normal proxy pipeline.
        # [LAW:one-source-of-truth] CONNECT routing is resolved once, then reused for every tunneled request.
        self._connect_target_host = route.upstream_origin

        try:
            while True:
                self.handle_one_request()
                if self.close_connection:
                    break
        except Exception:
            logger.exception(
                "Unhandled error while processing CONNECT tunnel for %s:%s",
                host,
                port,
            )
        finally:
            try:
                self.wfile.close()
            except Exception:
                pass
            try:
                self.rfile.close()
            except Exception:
                pass
            try:
                client_ssl.close()
            except Exception:
                pass

    def do_POST(self):
        self._proxy()

    def do_GET(self):
        self._proxy()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()


def make_handler_class(
    provider: str,
    target_host: str | None,
    event_queue: queue.Queue[PipelineEvent],
    request_pipeline: RequestPipeline = RequestPipeline(),
    forward_proxy_ca: "ForwardProxyCertificateAuthority | None" = None,
) -> type[ProxyHandler]:
    """Create a configured ProxyHandler subclass for a specific provider.

    // [LAW:one-type-per-behavior] All providers share one handler type,
    // parameterized by class attributes set here.
    // [LAW:dataflow-not-control-flow] Default request_pipeline is a module
    //   identity pipeline — never None, so the proxy interior is forbidden
    //   from asking "is the pipeline configured?". The default instance is
    //   treated as read-only by callers (RequestPipeline lists are not
    //   mutated after construction; they are replaced wholesale).
    """
    spec = cc_dump.providers.get_provider_spec(provider)
    return type(
        f"ProxyHandler_{spec.key}",
        (ProxyHandler,),
        {
            "provider": spec.key,
            "target_host": target_host.rstrip("/") if target_host else None,
            "event_queue": event_queue,
            "request_pipeline": request_pipeline,
            "forward_proxy_ca": forward_proxy_ca,
        },
    )
