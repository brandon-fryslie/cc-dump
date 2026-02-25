"""Copilot proxy plugin implementation.

// [LAW:locality-or-seam] Provider-specific HTTP behavior is isolated to this module.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request

import cc_dump.io.settings
from cc_dump.pipeline.event_types import (
    ErrorEvent,
    ProxyErrorEvent,
    ResponseCompleteEvent,
    ResponseDoneEvent,
    ResponseHeadersEvent,
    ResponseProgressEvent,
    parse_sse_event,
    sse_progress_payload,
)
from cc_dump.pipeline.response_assembler import ResponseAssembler
from cc_dump.proxies.copilot import provider as copilot_provider
from cc_dump.proxies.copilot.auth import run_device_auth_flow
from cc_dump.proxies.copilot.rate_limit import copilot_rate_limiter
from cc_dump.proxies.copilot.token_manager import resolve_copilot_token
from cc_dump.proxies.plugin_api import (
    ProxyAuthResult,
    ProxyProviderDescriptor,
    ProxyProviderPlugin,
    ProxyRequestContext,
    ProxySettingDescriptor,
)
from cc_dump.proxies.runtime import ProxyRuntime


_COPILOT_MESSAGES_PATH = "/v1/messages"
_COPILOT_COUNT_TOKENS_PATH = "/v1/messages/count_tokens"
_COPILOT_MODELS_PATHS = frozenset(("/v1/models", "/models"))
_COPILOT_CHAT_PATHS = frozenset(("/v1/chat/completions", "/chat/completions"))
_COPILOT_EMBEDDINGS_PATHS = frozenset(("/v1/embeddings", "/embeddings"))
_COPILOT_USAGE_PATHS = frozenset(("/usage", "/v1/usage"))
_COPILOT_TOKEN_PATHS = frozenset(("/token", "/v1/token"))
_COPILOT_SUPPORTED_PATHS = frozenset(
    {
        _COPILOT_MESSAGES_PATH,
        _COPILOT_COUNT_TOKENS_PATH,
        *_COPILOT_MODELS_PATHS,
        *_COPILOT_CHAT_PATHS,
        *_COPILOT_EMBEDDINGS_PATHS,
        *_COPILOT_USAGE_PATHS,
        *_COPILOT_TOKEN_PATHS,
    }
)
_COPILOT_RATE_LIMITED_PATHS = frozenset(
    {
        _COPILOT_MESSAGES_PATH,
        *_COPILOT_MODELS_PATHS,
        *_COPILOT_CHAT_PATHS,
        *_COPILOT_EMBEDDINGS_PATHS,
        *_COPILOT_USAGE_PATHS,
    }
)
_JSON_BODY_PATHS = frozenset(
    {
        _COPILOT_MESSAGES_PATH,
        _COPILOT_COUNT_TOKENS_PATH,
        *_COPILOT_CHAT_PATHS,
        *_COPILOT_EMBEDDINGS_PATHS,
    }
)


class CopilotProxyPlugin(ProxyProviderPlugin):
    @property
    def descriptor(self) -> ProxyProviderDescriptor:
        return ProxyProviderDescriptor(
            provider_id="copilot",
            display_name="Copilot",
            settings=(
                ProxySettingDescriptor(
                    key="proxy_copilot_base_url",
                    label="Copilot URL",
                    description="Base URL when provider=copilot",
                    kind="text",
                    default="https://api.githubcopilot.com",
                    env_vars=("CC_DUMP_COPILOT_BASE_URL",),
                ),
                ProxySettingDescriptor(
                    key="proxy_copilot_account_type",
                    label="Copilot Account",
                    description="individual | business | enterprise",
                    kind="select",
                    default="individual",
                    options=("individual", "business", "enterprise"),
                    env_vars=("CC_DUMP_COPILOT_ACCOUNT_TYPE",),
                ),
                ProxySettingDescriptor(
                    key="proxy_copilot_vscode_version",
                    label="VSCode Version",
                    description="Editor version string sent to Copilot API",
                    kind="text",
                    default="1.99.0",
                    env_vars=("CC_DUMP_COPILOT_VSCODE_VERSION",),
                ),
                ProxySettingDescriptor(
                    key="proxy_copilot_rate_limit_seconds",
                    label="Rate Limit (s)",
                    description="Minimum seconds between Copilot upstream calls (0 disables)",
                    kind="text",
                    default=0,
                    env_vars=("CC_DUMP_COPILOT_RATE_LIMIT_SECONDS",),
                ),
                ProxySettingDescriptor(
                    key="proxy_copilot_rate_limit_wait",
                    label="Wait On Limit",
                    description="When rate-limited, wait instead of returning 429",
                    kind="bool",
                    default=False,
                    env_vars=("CC_DUMP_COPILOT_RATE_LIMIT_WAIT",),
                ),
                ProxySettingDescriptor(
                    key="proxy_copilot_token",
                    label="Copilot Token",
                    description="Bearer token used for Copilot upstream requests",
                    kind="text",
                    default="",
                    secret=True,
                    env_vars=("GITHUB_COPILOT_TOKEN",),
                ),
                ProxySettingDescriptor(
                    key="proxy_copilot_github_token",
                    label="GitHub Token",
                    description="Fallback: fetch/refresh Copilot token from GitHub API",
                    kind="text",
                    default="",
                    secret=True,
                    env_vars=("CC_DUMP_COPILOT_GITHUB_TOKEN", "GITHUB_TOKEN"),
                ),
            ),
        )

    def handles_path(self, request_path: str) -> bool:
        return request_path in _COPILOT_SUPPORTED_PATHS

    def expects_json_body(self, request_path: str) -> bool:
        return request_path in _JSON_BODY_PATHS

    def run_auth_flow(self, *, force: bool) -> ProxyAuthResult:
        existing = str(cc_dump.io.settings.load_setting("proxy_copilot_github_token", "") or "").strip()
        if existing and not force:
            raise RuntimeError("Copilot GitHub token already configured. Use --proxy-auth-force to replace it.")
        device_code, github_token = run_device_auth_flow()
        runtime = ProxyRuntime()
        runtime.update_from_settings(
            {
                "proxy_provider": "copilot",
                "proxy_anthropic_base_url": "https://api.anthropic.com",
                "proxy_copilot_base_url": "https://api.githubcopilot.com",
                "proxy_copilot_token": "",
                "proxy_copilot_github_token": github_token,
                "proxy_copilot_account_type": "individual",
                "proxy_copilot_vscode_version": "1.99.0",
                "proxy_copilot_rate_limit_seconds": 0,
                "proxy_copilot_rate_limit_wait": False,
            }
        )
        token, error = resolve_copilot_token(runtime.snapshot())
        summary = (
            f"Authorized via device code {device_code.user_code} at {device_code.verification_uri}."
            if not error
            else (
                "Authorized, but Copilot token preflight failed: {}".format(error)
            )
        )
        if not error:
            summary += f" Copilot token preflight success (len={len(token)})."
        return ProxyAuthResult(
            settings_updates={
                "proxy_provider": "copilot",
                "proxy_copilot_github_token": github_token,
            },
            message=summary,
        )

    def handle_request(self, context: ProxyRequestContext) -> bool:
        if not self.handles_path(context.request_path):
            return False

        runtime_snapshot = context.runtime_snapshot
        request_id = context.request_id
        handler = context.handler
        body = context.request_body
        request_path = context.request_path

        if request_path in _COPILOT_RATE_LIMITED_PATHS:
            allowed, remaining = copilot_rate_limiter.gate(
                min_interval_seconds=runtime_snapshot.get_int("proxy_copilot_rate_limit_seconds", 0),
                wait_on_limit=runtime_snapshot.get_bool("proxy_copilot_rate_limit_wait", False),
            )
            if not allowed:
                message = (
                    "Copilot provider rate limit active; retry in {:.2f}s "
                    "(set proxy_copilot_rate_limit_wait=true to auto-wait)"
                ).format(remaining)
                context.event_queue.put(
                    ErrorEvent(
                        code=429,
                        reason=message,
                        request_id=request_id,
                        recv_ns=time.monotonic_ns(),
                    )
                )
                handler.send_response(429)
                handler.send_header("content-type", "application/json")
                handler.send_header("retry-after", str(int(max(1.0, remaining))))
                handler.end_headers()
                handler.wfile.write(
                    json.dumps(
                        {
                            "type": "error",
                            "error": {
                                "type": "rate_limit_error",
                                "message": message,
                            },
                        }
                    ).encode("utf-8")
                )
                return True

        if self.expects_json_body(request_path) and not isinstance(body, dict):
            context.event_queue.put(
                ErrorEvent(
                    code=400,
                    reason="Malformed JSON request body for Copilot provider",
                    request_id=request_id,
                    recv_ns=time.monotonic_ns(),
                )
            )
            handler.send_response(400)
            handler.send_header("content-type", "application/json")
            handler.end_headers()
            handler.wfile.write(
                json.dumps(
                    {
                        "type": "error",
                        "error": {
                            "type": "invalid_request_error",
                            "message": "Request body must be valid JSON object",
                        },
                    }
                ).encode("utf-8")
            )
            return True

        if request_path == _COPILOT_COUNT_TOKENS_PATH:
            payload = dict(body)
            beta_header = str(handler.headers.get("anthropic-beta", "")).strip()
            if beta_header:
                payload["_anthropic_beta"] = beta_header
            token_count = copilot_provider.count_tokens_for_messages(payload)
            response_body = {"input_tokens": token_count}
            data = json.dumps(response_body).encode("utf-8")
            handler.send_response(200)
            handler.send_header("content-type", "application/json")
            handler.send_header("content-length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            context.event_queue.put(
                ResponseHeadersEvent(
                    status_code=200,
                    headers={"content-type": "application/json"},
                    request_id=request_id,
                    seq=0,
                    recv_ns=time.monotonic_ns(),
                )
            )
            context.event_queue.put(
                ResponseCompleteEvent(
                    body=response_body,
                    request_id=request_id,
                    seq=1,
                    recv_ns=time.monotonic_ns(),
                )
            )
            return True

        if request_path in _COPILOT_EMBEDDINGS_PATHS:
            prepared_embeddings, error = copilot_provider.prepare_openai_embeddings_request(
                snapshot=runtime_snapshot,
                openai_payload=body,
            )
            if error is not None or prepared_embeddings is None:
                return self._auth_error(context, error or "Copilot auth configuration missing")
            request_bytes = json.dumps(prepared_embeddings.body).encode("utf-8")
            upstream_req = urllib.request.Request(
                prepared_embeddings.url,
                data=request_bytes,
                headers=prepared_embeddings.headers,
                method="POST",
            )
            return self._relay_non_stream_upstream(context, upstream_req)

        if request_path in _COPILOT_TOKEN_PATHS:
            token, error = resolve_copilot_token(runtime_snapshot)
            if error is not None:
                return self._auth_error(context, error)
            response_body = {"token": token}
            data = json.dumps(response_body).encode("utf-8")
            handler.send_response(200)
            handler.send_header("content-type", "application/json")
            handler.send_header("content-length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            context.event_queue.put(
                ResponseHeadersEvent(
                    status_code=200,
                    headers={"content-type": "application/json"},
                    request_id=request_id,
                    seq=0,
                    recv_ns=time.monotonic_ns(),
                )
            )
            context.event_queue.put(
                ResponseCompleteEvent(
                    body=response_body,
                    request_id=request_id,
                    seq=1,
                    recv_ns=time.monotonic_ns(),
                )
            )
            return True

        if request_path in _COPILOT_USAGE_PATHS:
            prepared_usage, error = copilot_provider.prepare_usage_request(snapshot=runtime_snapshot)
            if error is not None or prepared_usage is None:
                return self._auth_error(context, error or "Copilot GitHub auth missing for /usage")
            upstream_req = urllib.request.Request(
                prepared_usage.url,
                data=None,
                headers=prepared_usage.headers,
                method=prepared_usage.method,
            )
            return self._relay_non_stream_upstream(context, upstream_req)

        if request_path == "/v1/models":
            prepared_models, error = copilot_provider.prepare_models_request(snapshot=runtime_snapshot)
            if error is not None or prepared_models is None:
                return self._auth_error(context, error or "Copilot auth configuration missing")
            upstream_req = urllib.request.Request(
                prepared_models.url,
                data=None,
                headers=prepared_models.headers,
                method="GET",
            )
            try:
                ctx = ssl.create_default_context()
                resp = urllib.request.urlopen(upstream_req, context=ctx, timeout=300)
            except urllib.error.HTTPError as e:
                return self._relay_http_error(context, e)
            except Exception as e:  # pragma: no cover - defensive
                return self._relay_proxy_error(context, e)
            data = resp.read()
            try:
                copilot_models = json.loads(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                copilot_models = {}
            anthropic_models = (
                copilot_provider.translate_models_response(copilot_models)
                if isinstance(copilot_models, dict)
                else {"data": [], "has_more": False, "first_id": "", "last_id": ""}
            )
            output = json.dumps(anthropic_models).encode("utf-8")
            handler.send_response(resp.status)
            handler.send_header("content-type", "application/json")
            handler.send_header("content-length", str(len(output)))
            handler.end_headers()
            handler.wfile.write(output)
            context.event_queue.put(
                ResponseHeadersEvent(
                    status_code=resp.status,
                    headers={"content-type": "application/json"},
                    request_id=request_id,
                    seq=0,
                    recv_ns=time.monotonic_ns(),
                )
            )
            context.event_queue.put(
                ResponseCompleteEvent(
                    body=anthropic_models,
                    request_id=request_id,
                    seq=1,
                    recv_ns=time.monotonic_ns(),
                )
            )
            return True

        if request_path == "/models":
            prepared_models, error = copilot_provider.prepare_models_request(snapshot=runtime_snapshot)
            if error is not None or prepared_models is None:
                return self._auth_error(context, error or "Copilot auth configuration missing")
            upstream_req = urllib.request.Request(
                prepared_models.url,
                data=None,
                headers=prepared_models.headers,
                method="GET",
            )
            return self._relay_non_stream_upstream(context, upstream_req)

        if request_path in _COPILOT_CHAT_PATHS:
            prepared_openai, error = copilot_provider.prepare_openai_chat_request(
                snapshot=runtime_snapshot,
                openai_payload=body,
            )
            if error is not None or prepared_openai is None:
                return self._auth_error(context, error or "Copilot auth configuration missing")
            request_bytes = json.dumps(prepared_openai.body).encode("utf-8")
            upstream_req = urllib.request.Request(
                prepared_openai.url,
                data=request_bytes,
                headers=prepared_openai.headers,
                method="POST",
            )
            try:
                ctx = ssl.create_default_context()
                resp = urllib.request.urlopen(upstream_req, context=ctx, timeout=300)
            except urllib.error.HTTPError as e:
                return self._relay_http_error(context, e)
            except Exception as e:  # pragma: no cover - defensive
                return self._relay_proxy_error(context, e)
            if prepared_openai.stream:
                handler.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() != "transfer-encoding":
                        handler.send_header(k, v)
                handler.end_headers()
                context.event_queue.put(
                    ResponseHeadersEvent(
                        status_code=resp.status,
                        headers=context.safe_headers(resp.headers),
                        request_id=request_id,
                        seq=0,
                        recv_ns=time.monotonic_ns(),
                    )
                )
                self._stream_passthrough_response(context, resp)
                return True
            data = resp.read()
            handler.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() != "transfer-encoding":
                    handler.send_header(k, v)
            handler.end_headers()
            handler.wfile.write(data)
            try:
                parsed_body = json.loads(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                parsed_body = {}
            context.event_queue.put(
                ResponseHeadersEvent(
                    status_code=resp.status,
                    headers=context.safe_headers(resp.headers),
                    request_id=request_id,
                    seq=0,
                    recv_ns=time.monotonic_ns(),
                )
            )
            context.event_queue.put(
                ResponseCompleteEvent(
                    body=parsed_body,
                    request_id=request_id,
                    seq=1,
                    recv_ns=time.monotonic_ns(),
                )
            )
            return True

        prepared, error = copilot_provider.prepare_messages_request(
            snapshot=runtime_snapshot,
            anthropic_payload=body,
        )
        if error is not None or prepared is None:
            return self._auth_error(context, error or "Copilot auth configuration missing")

        request_bytes = json.dumps(prepared.body).encode("utf-8")
        upstream_req = urllib.request.Request(
            prepared.url,
            data=request_bytes,
            headers=prepared.headers,
            method="POST",
        )
        try:
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(upstream_req, context=ctx, timeout=300)
        except urllib.error.HTTPError as e:
            return self._relay_anthropic_http_error(context, e)
        except Exception as e:  # pragma: no cover - defensive
            return self._relay_proxy_error(context, e)

        if prepared.stream:
            handler.send_response(resp.status)
            handler.send_header("content-type", "text/event-stream")
            handler.send_header("cache-control", "no-cache")
            handler.end_headers()
            context.event_queue.put(
                ResponseHeadersEvent(
                    status_code=resp.status,
                    headers={"content-type": "text/event-stream"},
                    request_id=request_id,
                    seq=0,
                    recv_ns=time.monotonic_ns(),
                )
            )
            self._stream_copilot_response(context, resp)
            return True

        upstream_data = resp.read()
        try:
            openai_body = json.loads(upstream_data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            openai_body = {}
        anthropic_body = copilot_provider.translate_non_stream_response(openai_body)
        output_data = json.dumps(anthropic_body).encode("utf-8")
        handler.send_response(resp.status)
        handler.send_header("content-type", "application/json")
        handler.send_header("content-length", str(len(output_data)))
        handler.end_headers()
        handler.wfile.write(output_data)
        context.event_queue.put(
            ResponseHeadersEvent(
                status_code=resp.status,
                headers={"content-type": "application/json"},
                request_id=request_id,
                seq=0,
                recv_ns=time.monotonic_ns(),
            )
        )
        context.event_queue.put(
            ResponseCompleteEvent(
                body=anthropic_body,
                request_id=request_id,
                seq=1,
                recv_ns=time.monotonic_ns(),
            )
        )
        return True

    def _auth_error(self, context: ProxyRequestContext, message: str) -> bool:
        context.event_queue.put(
            ErrorEvent(
                code=401,
                reason=message,
                request_id=context.request_id,
                recv_ns=time.monotonic_ns(),
            )
        )
        context.handler.send_response(401)
        context.handler.send_header("content-type", "application/json")
        context.handler.end_headers()
        context.handler.wfile.write(
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "message": message,
                    },
                }
            ).encode("utf-8")
        )
        return True

    def _relay_non_stream_upstream(self, context: ProxyRequestContext, upstream_req: urllib.request.Request) -> bool:
        try:
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(upstream_req, context=ctx, timeout=300)
        except urllib.error.HTTPError as e:
            return self._relay_http_error(context, e)
        except Exception as e:  # pragma: no cover - defensive
            return self._relay_proxy_error(context, e)
        data = resp.read()
        context.handler.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() != "transfer-encoding":
                context.handler.send_header(k, v)
        context.handler.end_headers()
        context.handler.wfile.write(data)
        try:
            parsed_body = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed_body = {}
        context.event_queue.put(
            ResponseHeadersEvent(
                status_code=resp.status,
                headers=context.safe_headers(resp.headers),
                request_id=context.request_id,
                seq=0,
                recv_ns=time.monotonic_ns(),
            )
        )
        context.event_queue.put(
            ResponseCompleteEvent(
                body=parsed_body,
                request_id=context.request_id,
                seq=1,
                recv_ns=time.monotonic_ns(),
            )
        )
        return True

    def _relay_http_error(self, context: ProxyRequestContext, error: urllib.error.HTTPError) -> bool:
        context.event_queue.put(
            ErrorEvent(
                code=error.code,
                reason=error.reason,
                request_id=context.request_id,
                recv_ns=time.monotonic_ns(),
            )
        )
        context.handler.send_response(error.code)
        for k, v in error.headers.items():
            if k.lower() != "transfer-encoding":
                context.handler.send_header(k, v)
        context.handler.end_headers()
        context.handler.wfile.write(error.read())
        return True

    def _relay_anthropic_http_error(self, context: ProxyRequestContext, error: urllib.error.HTTPError) -> bool:
        error_bytes = error.read()
        try:
            openai_error_body = json.loads(error_bytes.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            openai_error_body = {}
        anthropic_error = copilot_provider.translate_error_response(
            openai_error_body if isinstance(openai_error_body, dict) else {},
            fallback_message=f"Copilot upstream HTTP {error.code}",
        )
        response_data = json.dumps(anthropic_error).encode("utf-8")
        context.event_queue.put(
            ErrorEvent(
                code=error.code,
                reason=error.reason,
                request_id=context.request_id,
                recv_ns=time.monotonic_ns(),
            )
        )
        context.handler.send_response(error.code)
        context.handler.send_header("content-type", "application/json")
        context.handler.send_header("content-length", str(len(response_data)))
        context.handler.end_headers()
        context.handler.wfile.write(response_data)
        return True

    def _relay_proxy_error(self, context: ProxyRequestContext, error: Exception) -> bool:
        context.event_queue.put(
            ProxyErrorEvent(
                error=str(error),
                request_id=context.request_id,
                recv_ns=time.monotonic_ns(),
            )
        )
        context.handler.send_response(502)
        context.handler.end_headers()
        return True

    def _stream_copilot_response(self, context: ProxyRequestContext, resp) -> None:
        assembler = ResponseAssembler()
        seq = 0
        stream_state = copilot_provider.stream_state()
        stream_error_event: dict | None = None
        try:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                if not payload:
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                translated_events = copilot_provider.translate_stream_chunk(
                    chunk_payload=chunk,
                    state=stream_state,
                )
                for event in translated_events:
                    event_type = str(event.get("type", ""))
                    raw = b"data: " + json.dumps(event).encode("utf-8") + b"\n\n"
                    context.handler.wfile.write(raw)
                    context.handler.wfile.flush()
                    if event_type:
                        assembler.on_event(event_type, event)
                        try:
                            sse = parse_sse_event(event_type, event)
                        except ValueError:
                            sse = None
                        payload = sse_progress_payload(sse) if sse is not None else None
                        if payload is not None:
                            seq += 1
                            context.event_queue.put(
                                ResponseProgressEvent(
                                    request_id=context.request_id,
                                    seq=seq,
                                    recv_ns=time.monotonic_ns(),
                                    **payload,
                                )
                            )
        except Exception:
            stream_error_event = copilot_provider.stream_error_event()
        finally:
            if stream_error_event is not None:
                error_type = str(stream_error_event.get("type", "error"))
                error_raw = b"data: " + json.dumps(stream_error_event).encode("utf-8") + b"\n\n"
                context.handler.wfile.write(error_raw)
                context.handler.wfile.flush()
                assembler.on_event(error_type, stream_error_event)
            context.handler.wfile.write(b"data: [DONE]\n\n")
            context.handler.wfile.flush()

        assembler.on_done()
        if assembler.result is not None:
            seq += 1
            context.event_queue.put(
                ResponseCompleteEvent(
                    body=assembler.result,
                    request_id=context.request_id,
                    seq=seq,
                    recv_ns=time.monotonic_ns(),
                )
            )
        seq += 1
        context.event_queue.put(
            ResponseDoneEvent(
                request_id=context.request_id,
                seq=seq,
                recv_ns=time.monotonic_ns(),
            )
        )

    def _stream_passthrough_response(self, context: ProxyRequestContext, resp) -> None:
        try:
            for raw_line in resp:
                context.handler.wfile.write(raw_line)
                context.handler.wfile.flush()
        finally:
            context.event_queue.put(
                ResponseDoneEvent(
                    request_id=context.request_id,
                    seq=1,
                    recv_ns=time.monotonic_ns(),
                )
            )


def create_plugin() -> ProxyProviderPlugin:
    # // [LAW:locality-or-seam] Factory is the seam used by generic registry discovery.
    return CopilotProxyPlugin()
