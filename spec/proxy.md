# HTTP Proxy

> Status: draft
> Last verified against: not yet

## Overview

Claude Code communicates with the Anthropic API (and optionally OpenAI-compatible providers) over HTTPS. Users cannot see what is being sent or received -- the system prompts, tool definitions, caching headers, and token counts are all invisible. cc-dump solves this by placing itself between the client and the upstream API, capturing every request and response in flight and emitting structured events for the TUI, analytics, and recording subsystems.

The proxy is the data source for the entire system. Nothing downstream -- formatting, rendering, analytics, recording -- has any other way to obtain API traffic. If the proxy does not capture it, it does not exist in cc-dump.

## Proxy Modes

cc-dump supports two proxy modes, determined per-provider:

### Reverse Proxy

The client sets an environment variable (e.g., `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`) so that API requests arrive at cc-dump as plain HTTP. cc-dump reads the request, forwards it upstream over HTTPS, and relays the response back to the client. The client never negotiates TLS with cc-dump -- TLS is between cc-dump and the upstream API only.

Used by: **Anthropic** (default provider), **OpenAI** (optional).

Environment variable per provider:

| Provider   | Env var              | Default target                      |
|------------|----------------------|-------------------------------------|
| Anthropic  | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com`         |
| OpenAI     | `OPENAI_BASE_URL`    | `https://api.openai.com/v1`         |

### Forward Proxy (CONNECT Tunneling)

Some clients (e.g., GitHub Copilot) do not support a configurable base URL but do support `HTTP_PROXY`/`HTTPS_PROXY`. For these, cc-dump acts as a forward proxy: the client issues an HTTP `CONNECT` request, cc-dump performs TLS interception using a locally generated CA certificate, and then routes decrypted HTTP requests through the same pipeline as reverse proxy traffic.

Used by: **Copilot** (optional).

Environment variables set by cc-dump for the client:

| Variable               | Value                                         |
|------------------------|-----------------------------------------------|
| `HTTP_PROXY`           | `http://127.0.0.1:<port>`                     |
| `HTTPS_PROXY`          | `http://127.0.0.1:<port>`                     |
| `NODE_EXTRA_CA_CERTS`  | Path to generated CA certificate PEM file     |

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

All provider metadata lives in a single canonical registry. Each provider is described by a `ProviderSpec` with these fields:

| Field                 | Purpose                                                    |
|-----------------------|------------------------------------------------------------|
| `key`                 | Unique identifier (e.g., `"anthropic"`, `"openai"`, `"copilot"`) |
| `display_name`        | Human-facing name                                          |
| `protocol_family`     | `"anthropic"` or `"openai"` -- determines SSE parsing and response assembly strategy |
| `api_paths`           | URL path prefixes that identify API traffic (e.g., `("/v1/messages",)`) |
| `proxy_type`          | `"reverse"` or `"forward"`                                 |
| `default_target`      | Default upstream URL                                       |
| `base_url_env`        | Environment variable the client reads to find the proxy    |
| `optional_proxy`      | Whether this provider can be disabled via `--no-<provider>` |
| `forward_proxy_hosts` | Allowed CONNECT hostnames (forward proxy mode only)        |
| `tab_title`           | Title string for the TUI tab                               |
| `tab_short_prefix`    | Short prefix for compact display                            |
| `har_request_url`     | URL template used when writing HAR entries                  |
| `client_hint`         | Hint text shown to the user for configuring their client    |
| `url_markers`         | Substrings used for best-effort provider inference from URLs |

### Registered Providers

| Key        | Protocol | Proxy Mode | API Paths                                   | Default Target                         |
|------------|----------|------------|---------------------------------------------|----------------------------------------|
| `anthropic`| anthropic| reverse    | `/v1/messages`                              | `https://api.anthropic.com`            |
| `openai`   | openai   | reverse    | `/v1/chat/completions`, `/chat/completions` | `https://api.openai.com/v1`            |
| `copilot`  | openai   | forward | `/chat/completions`, `/v1/chat/completions` | `https://api.githubcopilot.com`        |

The copilot provider has `proxy_type="forward"`. Its `default_target` is used for CONNECT host routing, not as a reverse proxy target. When `proxy_type` is `"forward"`, the `--copilot-target` flag is accepted but the target value is not used for URL construction -- the upstream URL is derived from the CONNECT authority instead.

## What Gets Intercepted

### Request Interception

When an HTTP request arrives (POST or GET), the proxy:

1. **Reads the full request body** from the socket.
2. **Resolves the upstream URL.** In reverse proxy mode, the request path is appended to the configured target host. If the client sends an absolute-form URL (e.g., `http://api.anthropic.com/v1/messages`), the URL is used directly (upgraded to HTTPS if needed). In forward proxy mode after CONNECT, requests are constrained to the origin established during the tunnel handshake.
3. **Determines if this is API traffic.** The request path is checked against the provider's `api_paths`. Only requests matching these prefixes are parsed as JSON and emit pipeline events. Non-API traffic (health checks, token counting endpoints, etc.) is forwarded transparently without generating events.
4. **Parses the request body as JSON** (for API paths only). The body must be a JSON object at the top level. Parse failures are logged but do not block forwarding.
5. **Emits pipeline events:** `RequestHeadersEvent` (with sensitive headers stripped), then `RequestBodyEvent` (with the parsed JSON body).
6. **Runs the request pipeline** (transforms + interceptors), if configured. Transforms modify the body/URL unconditionally. Interceptors can short-circuit the request with a synthetic response.
7. **Forwards the request upstream** over HTTPS using the system trust store (`truststore` library for platform-native CA bundle). Timeout: 300 seconds.

### Response Handling

Responses are handled differently based on content type:

**Streaming responses** (`Content-Type: text/event-stream`):

The proxy reads the SSE stream line by line, simultaneously:
- Writing raw bytes back to the client (standard `write()` + `flush()`, not zero-copy)
- Parsing `data:` lines as JSON events
- Feeding parsed events to a protocol-family-specific response assembler that reconstructs the complete message
- Emitting `ResponseProgressEvent` for each meaningful SSE event (text deltas, stop reasons, model identification)

When the stream ends (`data: [DONE]`), the proxy emits:
- `ResponseCompleteEvent` with the fully assembled response message
- `ResponseDoneEvent` to signal completion

The fan-out to multiple consumers (client relay, event emission, response assembly) uses per-sink error isolation -- a failure in one sink does not affect others.

**Non-streaming responses:**

The proxy reads the full response body, writes it to the client, parses it as JSON, and emits `ResponseHeadersEvent` followed by `ResponseCompleteEvent`. No `ResponseProgressEvent` or `ResponseDoneEvent` is emitted for non-streaming responses.

### Header Filtering

The following headers are stripped from emitted events (but still forwarded to the upstream/client):

- `authorization` -- API keys
- `x-api-key` -- API keys
- `cookie` / `set-cookie` -- session tokens
- `host` -- noise
- `content-length` -- noise
- `transfer-encoding` -- noise

This filtering is for event/display purposes only. When building upstream headers, the proxy strips `host` entirely and re-adds `Content-Length` based on the actual body size.

### CORS

The proxy responds to `OPTIONS` requests with permissive CORS headers (`Access-Control-Allow-Origin: *`). This exists to support textual-serve browser mode.

## TLS

### Upstream TLS (All Modes)

All upstream connections use HTTPS. The proxy creates an `ssl.SSLContext` via the `truststore` library, which delegates to the platform's native certificate store (macOS Keychain, Windows Certificate Store, or system CA bundle on Linux). This means cc-dump trusts the same CAs as the rest of the system without bundling its own CA certificates.

Timeout for upstream connections: 300 seconds.

### Forward Proxy TLS Interception

When a client sends a `CONNECT` request (forward proxy mode), cc-dump performs TLS man-in-the-middle interception:

1. **CONNECT authority parsing.** The proxy extracts `host:port` from the CONNECT request. Supports IPv4, IPv6 (`[::1]:443`), and hostname formats. Default port is 443 if omitted.
2. **Host validation.** The CONNECT host is checked against the provider's `forward_proxy_hosts` allowlist. Only explicitly listed hosts are permitted. Requests to unlisted hosts receive `403 Forbidden`.
3. **Tunnel establishment.** The proxy sends `200 Connection Established` to the client.
4. **Certificate generation.** A TLS certificate for the requested hostname is generated on-the-fly, signed by cc-dump's local CA. Certificates are cached per-hostname for the lifetime of the process.
5. **TLS handshake.** The client socket is wrapped with the generated certificate. If the handshake fails (e.g., client does not trust the CA), the tunnel is silently closed.
6. **Decrypted request processing.** After the handshake, the proxy reads decrypted HTTP requests from the tunnel and processes them through the normal proxy pipeline. The tunnel persists for multiple requests (HTTP keep-alive).

### Certificate Authority

The forward proxy CA is created on first use and persisted to disk:

- **Location:** `~/.cc-dump/forward-proxy-ca/` (configurable via `--forward-proxy-ca-dir`)
- **Files:** `ca.key` (private key, mode 0600), `ca.crt` (certificate, mode 0644)
- **CA validity:** 3 years
- **Per-host certificate validity:** 1 year
- **Key size:** 2048-bit RSA for both CA and per-host certificates
- **Per-host certificates** are written to a temporary directory that is cleaned up on process exit

The CA is only created when at least one active provider uses forward proxy mode. If all providers are reverse-proxy-only, no CA is generated.

For clients to trust the generated certificates, they must be configured to trust the CA certificate. cc-dump communicates this via `NODE_EXTRA_CA_CERTS` in the environment variables it suggests to the user.

## Request Pipeline

Before forwarding, API requests pass through an optional `RequestPipeline` with two phases:

1. **Transforms** run unconditionally in sequence. Each transform receives `(body, url)` and returns `(body, url)`. Transforms can modify the request body or redirect to a different URL. Every transform sees the output of the previous one.

2. **Interceptors** run after transforms. Each interceptor receives the (possibly transformed) body. The first interceptor to return a non-None string short-circuits: the request is not forwarded upstream, and the returned string becomes the content of a synthetic SSE response sent back to the client.

Synthetic responses from interceptors are formatted as valid Anthropic SSE streams (`message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`, `[DONE]`) and emit the same pipeline events as real responses. Downstream consumers cannot distinguish intercepted from real responses. The sentinel interceptor IS configured by default when a tmux controller is available.

## Protocol Family Handling

The proxy adapts its SSE parsing based on the provider's `protocol_family`:

### Anthropic Protocol

- SSE events have a `type` field (e.g., `message_start`, `content_block_delta`, `message_stop`)
- Progress extraction parses typed SSE events into `ResponseProgressEvent` payloads
- Response assembly reconstructs the complete `message` object from SSE fragments

### OpenAI Protocol

- SSE events follow the OpenAI chat completions streaming format: `{"id":"...","choices":[{"index":0,"delta":{"content":"..."}}]}`
- Progress extraction pulls `delta.content` for text, `finish_reason` for stop, and `model` for model identification
- Response assembly reconstructs the complete `chat.completion` object

The protocol family is resolved once from the provider spec and used to select the correct extractor and assembler. Both families share the same fan-out and event emission infrastructure.

## Error Handling

### Upstream HTTP Errors

When the upstream API returns an HTTP error (4xx, 5xx), the proxy:
- Emits an `ErrorEvent` with the status code and reason (only for requests that had API traffic)
- Relays the error response (status, headers, body) to the client unchanged

### Connection Failures

When the proxy cannot connect to the upstream API:
- Emits a `ProxyErrorEvent` with the exception message
- Returns `502 Bad Gateway` to the client

### Missing Target

When no target host is configured and the client sends a relative-path request:
- Emits an `ErrorEvent` with status 500
- Returns a message: "No target configured. Use --target or send absolute URIs."

### CONNECT Errors

| Condition                          | Response         |
|------------------------------------|------------------|
| Malformed CONNECT authority        | `400 Bad Request` |
| CONNECT in reverse-proxy-only mode | `501 Not Implemented` |
| Host not in provider's allowlist   | `403 Forbidden`  |
| TLS handshake failure              | Connection closed silently |

### Non-API Traffic

Requests that do not match the provider's `api_paths` are forwarded to the upstream and relayed back to the client, but produce no request/response pipeline events. However, a `LogEvent` is still emitted for every HTTP request via the `log_message()` override. This covers health check endpoints, token counting, and any other non-conversational traffic.

## Event Emission

For each API request/response cycle, the proxy emits events in this order:

```
RequestHeadersEvent    (seq=0, request headers with sensitive fields stripped)
RequestBodyEvent       (seq=1, parsed JSON body)
ResponseHeadersEvent   (seq=0, status code + response headers)
ResponseProgressEvent* (seq=1..N, one per meaningful SSE event, streaming only)
ResponseCompleteEvent  (seq=N+1, fully assembled response message)
ResponseDoneEvent      (seq=N+2, signals completion)
```

Every event carries:
- `request_id` -- unique per request, correlates all events in one cycle
- `seq` -- two independent counters: request-side (starting at 0 for headers, incrementing for body) and response-side (starting at 0 for response headers, incrementing through progress and completion). Not globally monotonic across the request/response boundary.
- `recv_ns` -- nanosecond timestamp
- `provider` -- provider key string

Additionally, a `LogEvent` is emitted for every HTTP request via the `log_message()` override, regardless of whether the request matches API paths.

Events are placed on a shared `queue.Queue` that the TUI's event router drains. The proxy never blocks on the queue -- it is fire-and-forget from the proxy's perspective.

## Multi-Provider Topology

When multiple providers are active (e.g., Anthropic + OpenAI + Copilot), each gets:
- Its own `ThreadingHTTPServer` on its own port
- Its own handler class (parameterized subclass of `ProxyHandler`)
- Its own target host and proxy mode

All providers share a single event queue. Events are tagged with the `provider` field so downstream consumers can distinguish traffic from different providers.

The default provider (Anthropic) is always active. Optional providers (OpenAI, Copilot) are active by default but can be disabled with `--no-openai` or `--no-copilot`.
