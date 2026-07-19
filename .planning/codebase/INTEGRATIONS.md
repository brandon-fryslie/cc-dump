# External Integrations

## API Providers

### Primary Integration: Anthropic Claude API
- **Endpoint**: `https://api.anthropic.com/v1/messages` (default)
- **Environment Variable**: `ANTHROPIC_BASE_URL`
- **Proxy Type**: Reverse HTTP proxy
- **Authentication**: Bearer token via `authorization` header (filtered from logs)
- **Module**: `src/cc_dump/providers.py`, key `"anthropic"`
- **Request Format**: Anthropic native JSON
- **Response Format**: Server-sent events (SSE) streaming
- **Client Implementation**: `urllib.request` for interception & forwarding

### Secondary Integration: OpenAI API
- **Endpoint**: `https://api.openai.com/v1/chat/completions` (default)
- **Environment Variable**: `OPENAI_BASE_URL`
- **Proxy Type**: Reverse HTTP proxy
- **Optional**: Disabled by default, enabled with `--no-openai` flag removal
- **Module**: `src/cc_dump/providers.py`, key `"openai"`
- **Request Format**: OpenAI chat completions JSON
- **Response Format**: SSE streaming or JSON response
- **Data Structure Mapping**: OpenAI messages map to Anthropic-compatible internal format

### Tertiary Integration: GitHub Copilot
- **Endpoint**: `https://api.githubcopilot.com/chat/completions` (default)
- **Environment Variable**: `COPILOT_PROXY_URL`
- **Proxy Type**: Forward HTTP proxy (CONNECT tunneling for TLS interception)
- **Optional**: Disabled by default
- **Module**: `src/cc_dump/providers.py`, key `"copilot"`
- **Request Format**: OpenAI-compatible JSON (format translation required)
- **Response Format**: SSE streaming
- **Special Handling**:
  - Forward proxy CA generates per-host certificates for CONNECT
  - `ForwardProxyCertificateAuthority` manages TLS interception
  - CA certificate path: `~/.cc-dump/forward-proxy-ca/ca.crt` (for `NODE_EXTRA_CA_CERTS`)

### Protocol Format Translations
- **Module**: `src/cc_dump/pipeline/copilot_translate.py`
- **Translation**: OpenAI chat completions ↔ Anthropic message format
- **Provider Spec Field**: `upstream_format` (values: `"anthropic"`, `"openai-chat"`, `"openai-responses"`)
- **Use Cases**:
  - Copilot proxy: OpenAI format → translate to Anthropic for display
  - Upstream preset: `--upstream copilot` sets target URL + upstream format

## HTTP Proxy Infrastructure

### Proxy Server
- **Type**: Reverse HTTP proxy (Anthropic, OpenAI) + Forward HTTP proxy (Copilot)
- **Implementation**: Python `http.server.ThreadingHTTPServer`
- **Handler**: `src/cc_dump/pipeline/proxy.py:ProxyHandler`
- **Features**:
  - Streaming request/response interception
  - SSE event parsing and forwarding
  - Request/response header sanitization (removes `authorization`, `cookie`, `set-cookie`, etc.)
  - Multi-provider port binding (each provider gets independent port)

### SSL/TLS Certificate Handling
- **Library**: `cryptography` + stdlib `ssl`
- **Forward Proxy CA**:
  - Module: `src/cc_dump/pipeline/forward_proxy_tls.py:ForwardProxyCertificateAuthority`
  - CA lifecycle: Create or load existing CA on startup
  - Per-host cert generation: On-demand RSA 2048-bit certificates
  - Storage: `~/.cc-dump/forward-proxy-ca/` (customizable)
  - Permissions: 0o700 for directory, 0o600 for keys, 0o644 for certs
  - Cache: In-memory `_host_contexts` dict for reuse
  - Cleanup: Ephemeral per-host certs in temp directory via `atexit`

### CONNECT Tunneling
- **Feature**: Forward proxy CONNECT method support for Copilot
- **Module**: `src/cc_dump/pipeline/proxy.py` (CONNECT handler)
- **Validation**:
  - `src/cc_dump/providers.py:resolve_forward_proxy_connect_route()`
  - Enforces `forward_proxy_hosts` whitelist per provider
- **Supported Hosts**: `api.githubcopilot.com`
- **Client Setup**:
  - CA cert at: `$NODE_EXTRA_CA_CERTS=~/.cc-dump/forward-proxy-ca/ca.crt`
  - Proxy URL: `http://127.0.0.1:<port>` (HTTP CONNECT proxy)

## Recording & Replay System

### HAR 1.2 Recording
- **Format**: HTTP Archive standard JSON
- **Module**: `src/cc_dump/pipeline/har_recorder.py:HARRecordingSubscriber`
- **Storage**: `~/.local/share/cc-dump/recordings/` (default)
- **Filename Pattern**: `ccdump-{provider}-{timestamp}-{hash}.har`
- **Streaming Handling**:
  - Accumulates SSE events during response
  - Reconstructs complete non-streaming message
  - Sets synthetic `stream: false` in HAR for clarity
- **Per-Provider Recording**: One HAR per active provider per session
- **One-Shot Commands**:
  - `cc-dump --list-recordings` — List available HAR files
  - `cc-dump --cleanup-recordings [N]` — Delete old recordings, keep N newest
  - `cc-dump --cleanup-dry-run` — Preview cleanup

### HAR Replay
- **Module**: `src/cc_dump/pipeline/har_replayer.py`
- **Loading**: Parses HAR JSON, extracts request/response pairs
- **Event Synthesis**: Reconstructs pipeline events from HAR
- **Integration**: Feeds replayed events to same router/pipeline as live mode
- **CLI Arguments**:
  - `cc-dump --replay <path.har>` — Replay specific HAR file
  - `cc-dump --resume [path]` — Auto-discover latest recording
  - `cc-dump --continue` — Replay latest + stay live for new requests
  - `cc-dump run <config> --resume latest` — Resume + auto-launch config

### Session Management
- **Module**: `src/cc_dump/io/sessions.py`
- **Discovery**: Scan recordings directory for HAR files
- **Time-Based Ordering**: Sort by timestamp for resume/continue operations
- **Cleanup Logic**: Atomic file deletion with size accounting

## File System Integration

### Settings Persistence
- **Path**: `$XDG_CONFIG_HOME/cc-dump/settings.json` (default: `~/.config/cc-dump/settings.json`)
- **Module**: `src/cc_dump/io/settings.py`
- **Format**: JSON key-value dictionary
- **Stored Values**:
  - Visibility levels (vis_headers, vis_user, vis_assistant, etc.)
  - Theme preference
  - Filter settings
  - Launch config preferences
- **Write Pattern**: Atomic (write temp file → rename)
- **Error Handling**: Gracefully defaults to empty dict on missing/corrupt files

### Recording Directory
- **Path**: `~/.local/share/cc-dump/recordings/`
- **Format**: HAR JSON files
- **Cleanup Policy**: Manual via `--cleanup-recordings` command
- **Size Management**: Logged via `io.sessions.format_size()`

### Forward Proxy CA Storage
- **Path**: `~/.cc-dump/forward-proxy-ca/` (customizable via `--forward-proxy-ca-dir`)
- **Files**:
  - `ca.key` — CA private key (PEM format)
  - `ca.crt` — CA certificate (PEM format)
- **Permission Hardening**: 0o600 for keys, 0o644 for certs, 0o700 for directory
- **Persistence**: Cached across sessions for consistent host certificates
- **Alternative**: Ephemeral per-host certs in platform temp directory

### Logging
- **Module**: `src/cc_dump/io/logging_setup.py`
- **Configuration**: Platform-specific (not XDG-standardized in current version)
- **Features**:
  - Stderr tee for capturing errors (module: `src/cc_dump/io/stderr_tee.py`)
  - Error log display in TUI

## System Integration

### Tmux Integration
- **Module**: `src/cc_dump/app/tmux_controller.py` (stable boundary, never hot-reloaded)
- **Library**: `libtmux` ≥0.30.0 (optional, graceful degradation)
- **Features**:
  - Launch external tools (e.g., Claude CLI) in tmux panes
  - Tool process tracking and status display
  - Split pane management
  - Zoom state cleanup on shutdown
- **State Machine**: `TmuxState` enum (NOT_IN_TMUX, NO_LIBTMUX, READY, TOOL_RUNNING)
- **Environment Detection**: Checks `$TMUX` environment variable
- **Error Handling**: Silently disables if libtmux not installed or not in tmux session

### Watch System
- **Library**: `watchfiles` ≥1.0.0
- **Use Case**: Hot-reload trigger in development mode
- **Watched Directory**: `src/cc_dump/`
- **Module**: `src/cc_dump/app/hot_reload.py`
- **Behavior**: Full reload on any file change (no incremental reload)

## Certificate Trust & Security

### System Certificate Store
- **Library**: `truststore` ≥0.10.4
- **Purpose**: OS-native SSL/TLS certificate validation
- **Integration**: Used by `urllib.request.HTTPSHandler` for API calls
- **Benefit**: Respects system proxy settings and CA bundle

### Custom CA for Forward Proxy
- **Module**: `src/cc_dump/pipeline/forward_proxy_tls.py`
- **Generation**: On-demand X.509 certificates for Copilot forward proxy
- **Signing Algorithm**: SHA256 with RSA
- **Key Size**: 2048-bit RSA (CA and per-host)
- **Validity**:
  - CA: 3 years (365 × 3 days)
  - Per-host: 1 year (365 days)
- **Attributes**:
  - Subject CN: `"cc-dump Forward Proxy CA"`
  - Self-signed CA (issuer = subject)
  - Basic constraints: CA=true
- **Usage Pattern**: Export `NODE_EXTRA_CA_CERTS=~/.cc-dump/forward-proxy-ca/ca.crt` for Node.js tools

## Authentication & Secrets

### API Keys
- **Mechanism**: HTTP `authorization` header (Bearer token)
- **Providers**:
  - Anthropic: ANTHROPIC_API_KEY (injected by client)
  - OpenAI: OPENAI_API_KEY (injected by client)
  - Copilot: Varies by client (Claude CLI, etc.)
- **Header Filtering**:
  - Module: `src/cc_dump/pipeline/proxy.py:_safe_headers()`
  - Excluded headers: `authorization`, `x-api-key`, `cookie`, `set-cookie`, `host`, `content-length`, `transfer-encoding`
  - Applied to all event emissions (prevents token leaks in recordings)

### Session Tokens
- **Storage**: Not stored by cc-dump
- **Lifecycle**: Client-managed (Claude CLI, IDE extensions, etc.)
- **Proxy Role**: Transparent forwarding with header sanitization

## Upstream Presets
- **Feature**: `--upstream <preset>` CLI flag
- **Defined in**: `src/cc_dump/cli.py:_UPSTREAM_PRESETS`
- **Available Presets**:
  - `copilot`: Target `https://api.individual.githubcopilot.com`, upstream format `openai-responses`
- **Behavior**: Overrides `--target` and sets `upstream_format` on default provider
- **Use Case**: One-command setup for known third-party providers

## Analytics & Diagnostics

### In-Memory Analytics Store
- **Module**: `src/cc_dump/app/analytics_store.py`
- **Scope**: Runtime-only, not persisted
- **Source of Truth**: HAR files (can be replayed to rebuild analytics)
- **Features**:
  - Token counting (heuristic: ~4 chars per token)
  - Tool invocation correlation
  - Session cost calculation
  - Turn metrics (sequence, latency, retry counts)
- **No Database**: Replaces SQLite with lightweight in-memory data structure
- **Event Processing**: `DirectSubscriber` to EventRouter for instant updates

### Performance Monitoring
- **Module**: `src/cc_dump/io/perf_logging.py`
- **Experiments**: `src/cc_dump/experiments/perf_metrics.py`, `memory_soak.py`
- **Tracing**: `tracemalloc` integration for memory profiling
- **Logging**: Platform logger integration

## Configuration Environment Variables

### API Endpoints
- `ANTHROPIC_BASE_URL` — Anthropic API base (default: `https://api.anthropic.com`)
- `OPENAI_BASE_URL` — OpenAI API base (default: `https://api.openai.com/v1`)
- `COPILOT_PROXY_URL` — Copilot forward proxy base (default: `https://api.githubcopilot.com`)

### System
- `XDG_CONFIG_HOME` — Settings directory (default: `~/.config`)
- `XDG_DATA_HOME` — Recording directory (default: `~/.local/share`)
- `TMUX` — Tmux session indicator (set by tmux)
- `NODE_EXTRA_CA_CERTS` — Additional CA certificates (for Node.js tools using forward proxy)

## Type Safety & Validation

### Pydantic Models
- **Module**: Throughout (event_types, error_models, etc.)
- **Use Cases**:
  - API request/response validation
  - Pipeline event dataclasses
  - Configuration objects
- **Validation**: Runtime type checking on model construction

## Testing Integrations

### Test Fixtures
- **HAR Test Data**: Fixture HAR files for replay testing
- **HTTP Client**: `requests` library for test assertions
- **PTY Driver**: `ptydriver` for subprocess testing (terminal I/O)
- **Async Testing**: `pytest-asyncio` for async function testing
- **Parallel Execution**: `pytest-xdist` for test parallelization

### Mock/Stub Strategy
- **Stubs Directory**: `stubs/` for type stubs
- **Direct Testing**: No mock libraries used (prefers direct integration tests)
