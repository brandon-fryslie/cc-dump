# HTTP Proxy

## Overview

Claude Code communicates with the Anthropic API (and optionally OpenAI-compatible providers) over HTTPS. Users cannot see what is being sent or received -- the system prompts, tool definitions, caching headers, and token counts are all invisible. cc-dump solves this by placing itself between the client and the upstream API, capturing every request and response in flight and emitting structured events for the TUI, analytics, and recording subsystems.

The proxy is the data source for the entire system. Nothing downstream -- formatting, rendering, analytics, recording -- has any other way to obtain API traffic. If the proxy does not capture it, it does not exist in cc-dump.

## Proxy Modes

cc-dump supports two proxy modes, determined per-provider:

### Reverse Proxy

The client sets an environment variable (e.g., `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`) so that API requests arrive at cc-dump as plain HTTP. cc-dump reads the request, forwards it upstream over HTTPS, and relays the response back to the client. The client never negotiates TLS with cc-dump -- TLS is between cc-dump and the upstream API only.

Used by: **Anthropic** (default provider), **OpenAI** (optional).

Environment variable per provider:

| Provider   | Env var (`base_url_env`) | Default target                      |
|------------|--------------------------|-------------------------------------|
| Anthropic  | `ANTHROPIC_BASE_URL`     | `https://api.anthropic.com`         |
| OpenAI     | `OPENAI_BASE_URL`        | `https://api.openai.com/v1`         |

### Forward Proxy (CONNECT Tunneling)

Some clients (e.g., GitHub Copilot) do not support a configurable base URL but do support `HTTP_PROXY`/`HTTPS_PROXY`. For these, cc-dump acts as a forward proxy: the client issues an HTTP `CONNECT` request, cc-dump performs TLS interception using a locally generated CA certificate, and then routes decrypted HTTP requests through the same pipeline as reverse proxy traffic.

Used by: **Copilot** (optional).

Environment variables emitted by cc-dump for the client (via `_provider_proxy_env_items` in `providers.py`):

| Variable               | Value                                         |
|------------------------|-----------------------------------------------|
| `HTTP_PROXY`           | `http://127.0.0.1:<port>`                     |
| `HTTPS_PROXY`          | `http://127.0.0.1:<port>`                     |
| `NODE_EXTRA_CA_CERTS`  | Path to generated CA certificate PEM file (only when CA cert path is available) |

Note: the copilot `ProviderSpec` has `base_url_env="COPILOT_PROXY_URL"`, but this field is not used for forward-proxy providers. The `_provider_proxy_env_items` function branches on `proxy_mode`: forward mode emits `HTTP_PROXY`/`HTTPS_PROXY`/`NODE_EXTRA_CA_CERTS`; reverse mode emits the provider's `base_url_env`.

## Port Assignment

By default, every proxy server binds to port `0`, which causes the OS to assign an available ephemeral port. The actual assigned port is read back from the socket after binding. This avoids port conflicts when running multiple cc-dump instances or alongside other services.

Users may specify explicit ports via CLI flags:

| Flag              | Applies to | Default |
|-------------------|-----------|---------|
| `--port <N>`      | Anthropic (default provider) | `0` (OS-assigned) |
| `--openai-port <N>` | OpenAI  | `0` (OS-assigned) |
| `--copilot-port <N>` | Copilot | `0` (OS-assigned) |

The bind address defaults to `127.0.0.1` (loopback only). It can be changed with `--host <addr>`.

Each provider gets its own `ThreadingHTTPServer` instance running in a dedicated daemon thread. The server is created, bound, and started before the TUI launches. The assigned port is captured and used to construct the `ProviderEndpoint` metadata that the TUI and launcher display to the user.

## Provider Registry

All provider metadata lives in a single canonical registry (`_PROVIDERS` dict in `providers.py`). Each provider is described by a `ProviderSpec` (frozen dataclass) with these fields:

| Field                 | Type                       | Purpose                                                    |
|-----------------------|----------------------------|------------------------------------------------------------|
| `key`                 | `str`                      | Unique identifier (e.g., `"anthropic"`, `"openai"`, `"copilot"`) |
| `display_name`        | `str`                      | Human-facing name (e.g., `"Anthropic"`, `"OpenAI"`, `"Copilot"`) |
| `protocol_family`     | `Literal["anthropic","openai"]` | Determines SSE parsing, progress extraction, and response assembly strategy |
| `api_paths`           | `tuple[str, ...]`          | URL path prefixes that identify API traffic (e.g., `("/v1/messages",)`) |
| `proxy_type`          | `Literal["reverse","forward"]` | `"reverse"` or `"forward"`                             |
| `default_target`      | `str`                      | Default upstream URL                                       |
| `base_url_env`        | `str`                      | Environment variable the client reads to find the proxy (reverse mode only) |
| `optional_proxy`      | `bool`                     | Whether this provider can be disabled via `--no-<provider>` |
| `forward_proxy_hosts` | `tuple[str, ...]`          | Allowed CONNECT hostnames (forward proxy mode only, default `()`) |
| `tab_title`           | `str`                      | Title string for the TUI tab                               |
| `tab_short_prefix`    | `str`                      | Short prefix for compact display (e.g., `"ANT"`, `"OAI"`, `"CPL"`) |
| `har_request_url`     | `str`                      | URL used when writing HAR entries for this provider        |
| `client_hint`         | `str`                      | Hint text shown to the user for configuring their client (default `"<your-tool>"`) |
| `url_markers`         | `tuple[str, ...]`          | Substrings used for best-effort provider inference from URLs |

### Registered Providers

| Key        | Protocol | Proxy Mode | API Paths                                   | Default Target                         | `base_url_env`        | `forward_proxy_hosts`           |
|------------|----------|------------|---------------------------------------------|----------------------------------------|-----------------------|---------------------------------|
| `anthropic`| anthropic| reverse    | `/v1/messages`                              | `https://api.anthropic.com`            | `ANTHROPIC_BASE_URL`  | (none)                          |
| `openai`   | openai   | reverse    | `/v1/chat/completions`, `/chat/completions` | `https://api.openai.com/v1`            | `OPENAI_BASE_URL`     | (none)                          |
| `copilot`  | openai   | forward    | `/chat/completions`, `/v1/chat/completions` | `https://api.githubcopilot.com`        | `COPILOT_PROXY_URL`   | `api.githubcopilot.com`         |

Additional per-provider values:

| Key        | `display_name` | `tab_title` | `tab_short_prefix` | `client_hint` | `url_markers`                                | `har_request_url`                                  | `optional_proxy` |
|------------|----------------|-------------|---------------------|---------------|----------------------------------------------|----------------------------------------------------|-------------------|
| `anthropic`| Anthropic      | Claude      | ANT                 | claude        | `api.anthropic.com`                          | `https://api.anthropic.com/v1/messages`            | false             |
| `openai`   | OpenAI         | OpenAI      | OAI                 | openai-api    | `api.openai.com`                             | `https://api.openai.com/v1/chat/completions`       | true              |
| `copilot`  | Copilot        | Copilot     | CPL                 | `<your-tool>` | `api.githubcopilot.com`, `githubcopilot.com` | `https://api.githubcopilot.com/chat/completions`   | true              |

### Supporting Types

**`ProviderEndpoint`** (frozen dataclass) -- resolved proxy endpoint metadata for one active provider:

| Field                       | Type   | Purpose                                              |
|-----------------------------|--------|------------------------------------------------------|
| `provider_key`              | `str`  | Provider key                                         |
| `proxy_url`                 | `str`  | Local proxy URL (e.g., `http://127.0.0.1:12345`)     |
| `target`                    | `str`  | Upstream target (empty for forward proxy)             |
| `proxy_mode`                | `str`  | `"reverse"` or `"forward"`                           |
| `forward_proxy_ca_cert_path`| `str`  | CA cert path (empty for reverse proxy)                |

**`ForwardProxyConnectRoute`** (frozen dataclass) -- resolved upstream route for one validated CONNECT tunnel:

| Field              | Type   | Purpose                                        |
|--------------------|--------|------------------------------------------------|
| `provider_key`     | `str`  | Provider key                                   |
| `upstream_origin`  | `str`  | Full upstream origin URL (e.g., `https://api.githubcopilot.com`) |

### Provider Inference

The registry supports provider inference from multiple sources (in precedence order, implemented in `detect_provider_from_har_entry`):

1. **Explicit metadata:** `_cc_dump.provider` field in HAR entries
2. **URL markers:** `url_markers` substring match against request URL
3. **Response shape:** Anthropic responses have `"type": "message"`, OpenAI responses have `"object": "chat.completion"`

Unknown URLs fall back to the default provider (`anthropic`) via `infer_provider_from_url`.

## What Gets Intercepted

### Request Interception

The handler implements `do_POST`, `do_GET`, and `do_OPTIONS`. Both `do_POST` and `do_GET` delegate to the same `_proxy()` method -- GET requests follow the identical code path as POST requests. In practice, GET requests have no body, so they never match API paths and produce only `LogEvent`.

When an HTTP request arrives (POST or GET), the proxy:

1. **Reads the full request body** from the socket.
2. **Resolves the upstream URL** (via `resolve_proxy_target_for_origin` in `proxy_flow.py`). Three cases:
   - **Absolute-form URL** (starts with `http://` or `https://`): the URL is used directly, upgraded to HTTPS if needed. Query strings are preserved.
   - **Relative path with target host configured**: the path is appended to `target_host`.
   - **Relative path without target host**: returns error (status 500).
   - **CONNECT tunnel active**: an additional origin constraint (`_constrain_target_origin`) ensures the request URL's origin matches the CONNECT tunnel's origin. Mismatches return `403`.
3. **Determines if this is API traffic.** The request path is checked against the provider's `api_paths` (via `_expects_json_body`). Only requests matching these prefixes are parsed as JSON and emit pipeline events. Non-API traffic (health checks, token counting endpoints, etc.) is forwarded transparently without generating events.
4. **Parses the request body as JSON** (for API paths only). Uses `parse_request_json` in `proxy_flow.py`. The body must be a JSON object at the top level (validated via pydantic `TypeAdapter(dict[str, object])`). Parse failures are logged but do not block forwarding.
5. **Emits pipeline events:** `RequestHeadersEvent` (seq=0, with sensitive headers stripped), then `RequestBodyEvent` (seq=1, with the parsed JSON body).
6. **Runs the request pipeline** (transforms + interceptors), if configured. Transforms modify the body/URL unconditionally. Interceptors can short-circuit the request with a synthetic response. The pipeline only runs when both a JSON body was parsed and a `RequestPipeline` is configured.
7. **Forwards the request upstream** over HTTPS using the system trust store (`truststore` library for platform-native CA bundle). Timeout: 300 seconds. The `Content-Length` header is rebuilt from the actual body size (which may differ after pipeline transforms).

### Response Handling

Responses are handled differently based on content type:

**Streaming responses** (`Content-Type: text/event-stream`):

The proxy uses `_fan_out_sse` to drive three `StreamSink` implementations simultaneously:

| Sink                  | Role                                                         |
|-----------------------|--------------------------------------------------------------|
| `ClientSink`          | Writes raw SSE bytes back to the HTTP client (`write()` + `flush()`) |
| `EventQueueSink`      | Parses SSE events, extracts progress payloads, emits `ResponseProgressEvent` to the event queue |
| Response assembler    | Accumulates SSE events into a complete response message       |

The assembler class is selected by protocol family:

| Protocol Family | Assembler Class                  | Output Shape              |
|-----------------|----------------------------------|---------------------------|
| `anthropic`     | `ResponseAssembler`              | Anthropic message object  |
| `openai`        | `OpenAiChatResponseAssembler`    | OpenAI chat.completion    |

Both assembler classes implement the `StreamSink` protocol (`on_raw`, `on_event`, `on_done`).

`_fan_out_sse` reads the response line by line. For each line:
1. Raw bytes are delivered to all sinks via `on_raw`.
2. Lines starting with `data: ` are extracted. `data: [DONE]` terminates the loop.
3. JSON-parseable data lines are delivered to all sinks via `on_event(event_type, event)`.

Per-sink error isolation: each sink call is wrapped in a try/except. A failure in one sink (e.g., client disconnect) does not affect other sinks. Failures are logged as warnings. This isolation matters because if the client disconnects mid-stream, the assembler and event queue sinks should still complete so the TUI and HAR recorder see the full response.

After the SSE stream completes, the proxy explicitly emits:
- `ResponseCompleteEvent` with the assembler's result (if any events were received)
- `ResponseDoneEvent` to signal completion

**Non-streaming responses:**

The proxy reads the full response body, writes it to the client, parses it as JSON (via `decode_json_response_body` in `proxy_flow.py` -- best-effort, returns `{}` on failure), and emits `ResponseHeadersEvent` followed by `ResponseCompleteEvent`. No `ResponseProgressEvent` or `ResponseDoneEvent` is emitted for non-streaming responses.

### Header Filtering

The following headers are stripped from emitted events (but still forwarded to the upstream/client). Defined as `_EXCLUDED_HEADERS` frozenset in `proxy.py`:

- `authorization` -- API keys
- `x-api-key` -- API keys
- `cookie` / `set-cookie` -- session tokens
- `host` -- noise
- `content-length` -- noise
- `transfer-encoding` -- noise

This filtering is applied via `_safe_headers()` for event/display purposes only. When building upstream headers (via `build_upstream_headers` in `proxy_flow.py`), `host` and `content-length` are stripped, and `Content-Length` is re-added based on the actual body size. `transfer-encoding` is also stripped from relayed response headers.

### CORS

The proxy responds to `OPTIONS` requests with permissive CORS headers (`Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: GET, POST, OPTIONS`, `Access-Control-Allow-Headers: *`). This exists to support textual-serve browser mode.

## TLS

### Upstream TLS (All Modes)

All upstream connections use HTTPS. The proxy creates an `ssl.SSLContext` via `truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)`, which delegates to the platform's native certificate store (macOS Keychain, Windows Certificate Store, or system CA bundle on Linux). This means cc-dump trusts the same CAs as the rest of the system without bundling its own CA certificates.

Timeout for upstream connections: 300 seconds (passed to `urllib.request.urlopen`).

### Forward Proxy TLS Interception

When a client sends a `CONNECT` request (forward proxy mode), cc-dump performs TLS man-in-the-middle interception:

1. **CONNECT authority parsing** (via `_parse_connect_authority`). The proxy extracts `host:port` from the CONNECT request line. Supports:
   - `host` (default port 443)
   - `host:port`
   - `[ipv6]` (default port 443)
   - `[ipv6]:port`
   - Port range validated: 1-65535.
   - Returns `None` (400 error) for malformed values, empty strings, or bare IPv6 without brackets (ambiguous colon).
2. **Host validation** (via `resolve_forward_proxy_connect_route` in `providers.py`). The CONNECT host is normalized (stripped of brackets, trailing dots, lowercased) and checked against the provider's `forward_proxy_hosts` allowlist. Only explicitly listed hosts are permitted. Requests to unlisted hosts receive `403 Forbidden`.
3. **Tunnel establishment.** The proxy sends `200 Connection Established` to the client.
4. **Certificate generation.** A TLS certificate for the requested hostname is generated on-the-fly by `ForwardProxyCertificateAuthority`, signed by cc-dump's local CA. SSL contexts are cached per-hostname (thread-safe via `threading.Lock`) for the lifetime of the process.
5. **TLS handshake.** The client socket is wrapped with `ctx.wrap_socket(self.connection, server_side=True)`. If the handshake fails (`ssl.SSLError`), the tunnel is silently closed (logged at debug level).
6. **Decrypted request processing.** After the handshake, the proxy replaces `self.connection`, `self.rfile`, and `self.wfile` with the decrypted socket/streams. The CONNECT route's `upstream_origin` is stored as `self._connect_target_host`. The proxy then loops calling `handle_one_request()` until `close_connection` is set, processing each decrypted request through the normal proxy pipeline. This supports HTTP keep-alive over the tunnel.

### Certificate Authority

The forward proxy CA is managed by `ForwardProxyCertificateAuthority` in `forward_proxy_tls.py`:

- **Location:** `~/.cc-dump/forward-proxy-ca/` (configurable via constructor `ca_dir` parameter, exposed via `--forward-proxy-ca-dir` CLI flag)
- **Directory permissions:** 0o700 (best-effort chmod)
- **Files:** `ca.key` (private key, mode 0o600), `ca.crt` (certificate, mode 0o644)
- **CA subject:** `CN=cc-dump Forward Proxy CA`
- **CA validity:** 3 years (`_CA_VALIDITY_DAYS = 365 * 3`)
- **Per-host certificate validity:** 1 year (`_HOST_VALIDITY_DAYS = 365`)
- **Key size:** 2048-bit RSA for both CA and per-host certificates
- **Clock skew protection:** both CA and per-host certificates have `not_valid_before` set to `now - 5 minutes`
- **Signing algorithm:** SHA-256
- **Per-host certificates** are written to a temporary directory (`tempfile.mkdtemp(prefix="cc-dump-forward-proxy-")`) that is cleaned up on process exit via `atexit.register(shutil.rmtree, ...)`
- **Per-host certificate filenames** use a `<sanitized-hostname>-<sha256-prefix>.crt/.key` pattern to avoid collisions
- **SAN (Subject Alternative Name):** per-host certs include a SAN extension -- `IPAddress` for IP addresses, `DNSName` for hostnames
- **Hostname normalization:** brackets stripped, IDNA encoding attempted, fallback to raw string

The CA is only created when at least one active provider uses forward proxy mode. If all providers are reverse-proxy-only, no CA is generated.

For clients to trust the generated certificates, they must be configured to trust the CA certificate. cc-dump communicates this via `NODE_EXTRA_CA_CERTS` in the environment variables it suggests to the user.

## Request Pipeline

Before forwarding, API requests pass through a `RequestPipeline` with two phases:

1. **Transforms** run unconditionally in sequence. Each transform receives `(body: dict, url: str)` and returns `(dict, str)`. Transforms can modify the request body or redirect to a different URL. Every transform sees the output of the previous one.

2. **Interceptors** run after transforms. Each interceptor receives the (possibly transformed) `body: dict`. The first interceptor to return a non-None string short-circuits: the request is not forwarded upstream, and the returned string becomes the content of a synthetic SSE response sent back to the client.

The pipeline only runs when the request body was successfully parsed as JSON. If the JSON body is None (non-API path or parse failure), the pipeline is skipped entirely.

### Synthetic Responses

Synthetic responses from interceptors (via `_build_synthetic_sse_bytes` and `_send_synthetic_response`) are formatted as valid Anthropic SSE streams:

```
message_start  (id=msg_synthetic_<uuid>, model from request body, usage all zeros)
content_block_start (index=0, type=text)
content_block_delta (index=0, full interceptor text in one delta)
content_block_stop  (index=0)
message_delta  (stop_reason=end_turn, output_tokens=1)
message_stop
[DONE]
```

The synthetic response emits the same pipeline events as real responses: `ResponseHeadersEvent`, `ResponseProgressEvent` (one per meaningful SSE event), `ResponseCompleteEvent`, and `ResponseDoneEvent`. The synthetic SSE bytes are re-parsed through a `ResponseAssembler` to produce the complete response body. Downstream consumers cannot distinguish intercepted from real responses.

**Limitation:** Synthetic responses always use `ResponseAssembler` (Anthropic format) regardless of the provider's protocol family. If an OpenAI-family provider triggers a sentinel, the `ResponseCompleteEvent.body` will have Anthropic message shape (`{type: "message", content: [...]}`) rather than OpenAI chat completion shape (`{object: "chat.completion", choices: [...]}`).

### Default Pipeline Configuration

The `RequestPipeline` is always created (in `cli.py`) with a single interceptor: the sentinel interceptor (from `sentinel.py`). This interceptor detects `$$` prefixes in the last user message of the request body. When triggered, it:
1. Optionally focuses the cc-dump tmux pane (when a tmux controller is available)
2. Returns `"[cc-dump]"` as the synthetic response text

The sentinel interceptor is always active regardless of whether tmux is available. The tmux pane focus is the optional part.

The same `RequestPipeline` instance is shared across all provider handler classes.

## Protocol Family Handling

The proxy adapts its SSE processing based on the provider's `protocol_family`. Two dispatch tables select the correct strategy:

### Progress Extraction

`_PROGRESS_EXTRACTORS_BY_FAMILY` maps protocol family to a function `(event_type: str, event: dict) -> dict | None`:

**Anthropic** (`_extract_anthropic_progress`):
- Delegates to `parse_sse_event` + `sse_progress_payload` from `event_types.py`
- Extracts: model + usage from `message_start`, delta text from `content_block_delta` (text type), stop reason + output tokens from `message_delta`, task tool use ID from `content_block_start` (tool_use type, name="Task")
- Returns `None` for unknown event types (caught via `ValueError` from `parse_sse_event`)

**OpenAI** (`_extract_openai_chat_progress`):
- Extracts from first choice: `delta.content` for text, `finish_reason` for stop reason, `model` from top-level event
- Returns the first non-None candidate payload (priority: delta text > finish reason > model)

### Response Assembly

`_ASSEMBLER_CLASSES_BY_FAMILY` maps protocol family to assembler class:

**Anthropic** (`ResponseAssembler`):
- Accumulates raw SSE event dicts, calls `reconstruct_message_from_events` on `on_done`
- Produces a message dict with: `id`, `type: "message"`, `role`, `content` (list of text/tool_use blocks), `model`, `stop_reason`, `stop_sequence`, `usage`
- Tool use blocks accumulate `input_json_delta` fragments, parsed on `content_block_stop`

**OpenAI** (`OpenAiChatResponseAssembler`):
- Accumulates streaming chunks, calls `_reconstruct_openai_chat_message` on `on_done`
- Produces a dict with: `id`, `object: "chat.completion"`, `model`, `choices` (with `message` containing `role`, `content`, optional `tool_calls`), `usage`
- Tool calls are accumulated by index, with function name and arguments fragments merged

Both families share the same fan-out infrastructure (`_fan_out_sse`) and event emission logic.

## Error Handling

### Upstream HTTP Errors

When the upstream API returns an HTTP error (4xx, 5xx), the proxy:
- Emits an `ErrorEvent` with the status code and reason (only for requests that emitted request events, i.e., API traffic with parsed JSON body)
- Relays the error response (status, headers, body) to the client unchanged
- `transfer-encoding` headers are stripped from relayed error response headers

### Connection Failures

When the proxy cannot connect to the upstream API (any exception other than `HTTPError`):
- Emits a `ProxyErrorEvent` with the exception message (only for API traffic)
- Returns `502 Bad Gateway` to the client (no body)

### Missing Target

When no target host is configured and the client sends a relative-path request:
- Emits an `ErrorEvent` with status 500
- Returns a message: "No target configured. Use --target or send absolute URIs."

### CONNECT Errors

| Condition                          | Response         |
|------------------------------------|------------------|
| Malformed CONNECT authority        | `400 Bad Request` |
| CONNECT without `forward_proxy_ca` | `501 Not Implemented` |
| Host not in provider's allowlist   | `403 Forbidden`  |
| TLS handshake failure (`SSLError`) | Connection closed silently (debug log) |
| Unhandled error in tunnel loop     | Logged via `logger.exception`, streams closed |

### Non-API Traffic

Requests that do not match the provider's `api_paths` are forwarded to the upstream and relayed back to the client, but produce no request/response pipeline events (no `RequestHeadersEvent`, `RequestBodyEvent`, `ResponseHeadersEvent`, `ResponseCompleteEvent`, etc.). Error events (`ErrorEvent`, `ProxyErrorEvent`) are also suppressed for non-API traffic. However, a `LogEvent` is still emitted for every HTTP request via the `log_message()` override. This covers health check endpoints, token counting, and any other non-conversational traffic.

## Event Emission

### Streaming API Request/Response Cycle

```
RequestHeadersEvent    (seq=0, request headers with sensitive fields stripped)
RequestBodyEvent       (seq=1, parsed JSON body)
ResponseHeadersEvent   (seq=0, status code + response headers)
ResponseProgressEvent* (seq=1..N, one per meaningful SSE event)
ResponseCompleteEvent  (seq=N+1, fully assembled response message)
ResponseDoneEvent      (seq=N+2, signals stream completion)
```

### Non-Streaming API Request/Response Cycle

```
RequestHeadersEvent    (seq=0, request headers with sensitive fields stripped)
RequestBodyEvent       (seq=1, parsed JSON body)
ResponseHeadersEvent   (seq=0, status code + response headers)
ResponseCompleteEvent  (seq=1, parsed JSON response body)
```

No `ResponseProgressEvent` or `ResponseDoneEvent` is emitted for non-streaming responses.

### Event Envelope

Every event carries these base fields (defined on `PipelineEvent` base class, populated by `event_envelope` helper):

| Field        | Type   | Source                                |
|--------------|--------|---------------------------------------|
| `request_id` | `str`  | UUID hex, unique per request cycle    |
| `seq`        | `int`  | Sequence counter (see below)          |
| `recv_ns`    | `int`  | `time.monotonic_ns()` at emission time |
| `provider`   | `str`  | Provider key string                   |

Sequence numbering uses two independent counters: request-side (starting at 0 for headers, 1 for body) and response-side (starting at 0 for response headers, incrementing through progress and completion). The counters are not globally monotonic across the request/response boundary.

### LogEvent

A `LogEvent` is emitted for every HTTP request via the `log_message()` override, regardless of whether the request matches API paths. It carries `method`, `path`, `status`, and `provider`.

### Queue Semantics

Events are placed on a shared `queue.Queue` that the event router drains. The proxy never blocks on the queue -- it is fire-and-forget from the proxy's perspective. The queue is shared across all provider servers.

## Event Router

The `EventRouter` (in `router.py`) drains the shared source queue and fans out to subscribers:

- Runs in its own daemon thread
- Polls the source queue with 0.5-second timeout
- Fans out each event to all subscribers via `on_event(event)`
- Per-subscriber error isolation: one subscriber's exception does not affect others (logged via `logger.exception`)
- Stops gracefully via `threading.Event` signal with 2-second join timeout

Two subscriber types:

| Type               | Behavior                                          |
|--------------------|---------------------------------------------------|
| `QueueSubscriber`  | Puts events into its own `queue.Queue` for async consumption |
| `DirectSubscriber` | Calls a function inline in the router thread       |

## Handler Factory

`make_handler_class` creates a parameterized `ProxyHandler` subclass for each provider. It uses `type()` to dynamically create a class named `ProxyHandler_<key>` with class-level attributes:

| Attribute          | Source                                        |
|--------------------|-----------------------------------------------|
| `provider`         | `spec.key`                                    |
| `target_host`      | Target URL with trailing `/` stripped, or None |
| `event_queue`      | Shared event queue                            |
| `request_pipeline` | Shared pipeline (set later by CLI)            |
| `forward_proxy_ca` | CA instance or None                           |

This ensures all providers share one handler implementation type, parameterized by class attributes.

## Multi-Provider Topology

When multiple providers are active (e.g., Anthropic + OpenAI + Copilot), each gets:
- Its own `ThreadingHTTPServer` on its own port
- Its own handler class (parameterized subclass of `ProxyHandler` via `make_handler_class`)
- Its own target host and proxy mode

All providers share:
- A single event queue
- A single `RequestPipeline` instance (with the sentinel interceptor)
- A single `ForwardProxyCertificateAuthority` instance (if any provider uses forward proxy mode)

Events are tagged with the `provider` field so downstream consumers can distinguish traffic from different providers.

The default provider (Anthropic) is always active (`optional_proxy=False`). Optional providers (OpenAI, Copilot) are active by default but can be disabled with `--no-openai` or `--no-copilot`.

## Source Files

| File | Role |
|------|------|
| `src/cc_dump/pipeline/proxy.py` | HTTP handler, SSE fan-out, synthetic responses, request pipeline |
| `src/cc_dump/pipeline/proxy_flow.py` | Pure planning: URL resolution, JSON parsing, header building |
| `src/cc_dump/pipeline/forward_proxy_tls.py` | CA lifecycle, per-host cert generation, SSL context caching |
| `src/cc_dump/providers.py` | Provider registry, endpoint metadata, CONNECT routing, provider inference |
| `src/cc_dump/pipeline/router.py` | Event queue fan-out to subscribers |
| `src/cc_dump/pipeline/event_types.py` | Pipeline event types, SSE event types, envelope helper |
| `src/cc_dump/pipeline/response_assembler.py` | SSE-to-complete-response reconstruction (Anthropic + OpenAI) |
| `src/cc_dump/pipeline/sentinel.py` | Sentinel interceptor (`$$` prefix detection) |
