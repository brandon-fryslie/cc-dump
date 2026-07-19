# Technology Stack

## Language & Runtime

- **Python** 3.10+ (requires >=3.10)
  - Supported versions: 3.10, 3.11, 3.12
  - Type checking: `mypy` with strict settings
  - Packaging: `hatchling` build backend

## Core Dependencies

### UI/TUI Framework
- **textual** ≥0.80.0 — Terminal UI framework
  - Custom widgets: `ConversationView` (virtual rendering via Line API)
  - Pre-rendered `Strip` objects for performance (conversation history caching)
  - Reactive state management via `@reactive` decorator
  - Custom `Footer` widget with private API access (`FooterKey`, `KeyGroup`, `FooterLabel`)
  - Textual Module Integration: `snarfx.textual` for reactive/observer pattern

- **textual-serve** ≥1.0.0 — Browser-based Textual interface
  - Enables `cc-dump-serve` command for web access at `http://localhost:8000`
  - Each browser session launches independent cc-dump instance

### State Management
- **snarfx** ≥0.1.0 — MobX-inspired reactive library (separate git repo)
  - Core: `Observable`, `Computed`, `Reaction`, `Store`, `HotReloadStore`
  - Integration: `snarfx.textual` module with `reaction()`, `autorun()`, `pause()`, `is_safe()`
  - Guards `NoMatches` exceptions and handles thread marshaling
  - Used for: view state (`vis_*` visibility levels), settings store, tmux state

### Network & HTTP
- **truststore** ≥0.10.4 — System certificate store integration
  - OS-specific SSL/TLS certificate handling

- **urllib** (stdlib) — HTTP proxy implementation
  - `urllib.request.HTTPHandler`, `urllib.error`
  - Core proxy: `http.server.ThreadingHTTPServer` + `http.server.BaseHTTPRequestHandler`
  - Streaming SSE response handling
  - Forward proxy CONNECT tunneling support

- **ssl** (stdlib) — TLS/SSL certificate management
  - Integrated with `cryptography` for custom CA generation

### Cryptography
- **cryptography** ≥42.0.0 — X.509 certificate generation
  - Forward proxy CA (Certificate Authority) for CONNECT interception
  - Per-host certificate generation with RSA 2048-bit keys
  - Extensions: `x509.BasicConstraints`, `x509.SubjectKeyIdentifier`

### Data & Configuration
- **pydantic** ≥2.8.2 — Data validation and serialization
  - Configuration models, API request/response validation
  - Type-safe model definitions for pipeline events

### System Integration
- **libtmux** ≥0.30.0 — Tmux pane management (optional)
  - Launch external tools (Claude CLI, other agents) in tmux panes
  - Split pane UI, process tracking
  - Graceful degradation when not in tmux or library unavailable

- **watchfiles** ≥1.0.0 — File system monitoring
  - Hot-reload trigger for development mode
  - Watches `src/cc_dump/` for changes

## Project Structure

```
src/cc_dump/
├── cli.py                          # Entry point, CLI argument parsing
├── serve.py                        # Web server entry (textual-serve)
├── providers.py                    # Provider registry (Anthropic, OpenAI, Copilot)
├── pipeline/                       # HTTP interception & event pipeline
│   ├── proxy.py                    # HTTP proxy handler, ProxyHandler class
│   ├── proxy_flow.py              # Proxy flow routing
│   ├── forward_proxy_tls.py       # Forward proxy CA & CONNECT interception
│   ├── router.py                  # EventRouter, QueueSubscriber, DirectSubscriber
│   ├── event_types.py             # Dataclass definitions for pipeline events
│   ├── har_recorder.py            # HAR 1.2 format recording
│   ├── har_replayer.py            # HAR replay (session resume)
│   ├── response_assembler.py      # SSE stream reconstruction
│   ├── copilot_translate.py       # OpenAI format translation
│   └── sentinel.py                # Request interceptors
├── core/                           # Business logic (format-agnostic)
│   ├── formatting.py              # FormattedBlock hierarchy (IR)
│   ├── formatting_impl.py         # Provider-specific formatting logic
│   ├── analysis.py                # Token estimation, budgets, tool correlation
│   ├── token_counter.py           # Token counting API
│   ├── palette.py                 # Color palette management
│   ├── filter_registry.py         # Search filters
│   ├── special_content.py         # Special content type handling
│   ├── coerce.py                  # Type coercion utilities
│   └── segmentation.py            # Text segmentation
├── tui/                            # Textual UI layer
│   ├── app.py                     # CcDumpApp main application
│   ├── rendering.py               # FormattedBlock → Rich text rendering
│   ├── rendering_impl.py          # Rendering implementation details
│   ├── widget_factory.py          # ConversationView, TurnData
│   ├── custom_footer.py           # Custom Footer widget
│   ├── action_handlers.py         # Keyboard action handlers
│   ├── event_handlers.py          # Event queue draining
│   ├── search.py                  # Search implementation
│   ├── search_controller.py       # Search state management
│   ├── input_modes.py             # Input mode state machine
│   ├── panel_registry.py          # Panel management
│   ├── panel_renderers.py         # Panel-specific renderers
│   ├── session_panel.py           # Session/info panel
│   ├── info_panel.py              # Info/metadata panel
│   ├── settings_panel.py          # Settings UI panel
│   ├── launch_config_panel.py     # Launch config UI panel
│   ├── keys_panel.py              # Keybindings reference panel
│   ├── debug_settings_panel.py    # Debug settings panel
│   ├── error_indicator.py         # Error display widget
│   ├── stream_registry.py         # Stream UI state
│   ├── theme_controller.py        # Theme/palette switching
│   ├── hot_reload_controller.py   # Hot-reload management
│   ├── lifecycle_controller.py    # App lifecycle (startup/shutdown)
│   ├── settings_launch_controller.py  # Settings/launch integration
│   ├── dump_export.py             # Session export to JSON
│   ├── dump_formatting.py         # Export formatting
│   ├── location_navigation.py     # Location tracking (thread IDs, etc.)
│   ├── prefix_sum_tree.py         # Line-to-turn binary search
│   ├── protocols.py               # Type protocols
│   ├── action_config.py           # Action configuration
│   ├── view_overrides.py          # View override management
│   └── category_config.py         # Category configuration
├── app/                            # Application state management
│   ├── analytics_store.py         # In-memory analytics (runtime-only, not persisted to DB)
│   ├── view_store.py              # SnarfX Store for visibility levels
│   ├── settings_store.py          # SnarfX Store for user settings
│   ├── domain_store.py            # FormattedBlock tree ownership
│   ├── hot_reload.py              # Hot-reload module orchestration
│   ├── tmux_controller.py         # Tmux integration (stable boundary)
│   ├── launch_config.py           # Launch configuration management
│   ├── launcher_registry.py       # Launcher registry
│   ├── memory_stats.py            # Memory profiling
│   ├── error_models.py            # Error type definitions
│   └── domain_store.py            # Domain object ownership
├── io/                             # I/O & external interfaces
│   ├── settings.py                # XDG settings file management
│   ├── sessions.py                # Recording management & playback
│   ├── logging_setup.py           # Logger configuration
│   ├── perf_logging.py            # Performance metrics
│   ├── stderr_tee.py              # Stderr capture for error display
│   └── __init__.py                # I/O module exports
└── experiments/                    # Experimental features
    ├── memory_soak.py             # Memory usage experiments
    ├── perf_metrics.py            # Performance metrics
    └── subagent_enrichment.py     # Subagent analysis
```

## Configuration Files

### Build & Packaging
- **pyproject.toml** — Project metadata, dependencies, build config
  - Package name: `cc-dump`
  - Version: 0.2.0
  - Scripts: `cc-dump` (CLI), `cc-dump-serve` (web)

### Runtime Configuration
- **Settings File**: `$XDG_CONFIG_HOME/cc-dump/settings.json` (or `~/.config/cc-dump/settings.json`)
  - Stores: visibility levels, theme preference, filter settings
  - Format: JSON key-value pairs
  - Atomic writes (temp file → rename)

- **Recording Storage**: `~/.local/share/cc-dump/recordings/`
  - HAR 1.2 format files (JSON)
  - Filename pattern: `ccdump-{provider}-{timestamp}-{hash}.har`
  - Indexed by creation time for resume/continue operations

- **Forward Proxy CA**: `~/.cc-dump/forward-proxy-ca/` (or custom via `--forward-proxy-ca-dir`)
  - `ca.key` — CA private key (2048-bit RSA, permissions 0o600)
  - `ca.crt` — CA certificate (permissions 0o644)
  - Per-host certs cached in temp directory

- **Logging**: Platform-specific
  - File location configured by `io.logging_setup`
  - Level: Configurable (default depends on mode)

## Build & Test Infrastructure

### Testing
- **pytest** ≥9.0.2 — Test runner
  - Async mode: `pytest-asyncio` ≥0.24.0
  - Parallelization: `pytest-xdist` ≥3.5.0
  - PTY driver: `ptydriver` ≥0.2.0 (subprocess PTY testing)
  - Test markers: `pty` (slow), `textual` (fast)

- **mypy** ≥1.10.0 — Static type checking
  - Config: strict settings with specific disabled error codes
  - Stub path: `stubs/`
  - Disables: dict-item, arg-type, union-attr, attr-defined (dynamic attribute issues)

### Development Dependencies
- **requests** ≥2.31.0 — HTTP client for testing
  - Test fixtures for HAR replay validation

## Key Architectural Patterns

### Two-Stage Pipeline
1. **Formatting Stage** (`core/formatting.py`):
   - API JSON → FormattedBlock IR (intermediate representation)
   - Provider-agnostic data model

2. **Rendering Stage** (`tui/rendering.py`):
   - FormattedBlock IR → Rich text for terminal display
   - Visibility level dispatch (EXISTENCE, SUMMARY, FULL)
   - Category-based truncation

### Event Flow
```
proxy.py (HTTP intercept)
  → router.py (EventRouter fan-out)
    → analytics_store.py (DirectSubscriber, in-memory)
    → display_sub (QueueSubscriber, async TUI consumption)
    → har_recorder.py (DirectSubscriber, inline HAR writes)
```

### Recording System
- **Live Mode**: `har_recorder.py` subscribes to events
  - Accumulates SSE streams
  - Reconstructs complete messages
  - Writes HAR 1.2 format
- **Replay Mode**: `har_replayer.py` loads HAR
  - Synthesizes events from HAR
  - Feeds to same router/pipeline as live mode

### Virtual Rendering
- `ConversationView` uses Textual's Line API
- `TurnData` stores pre-rendered `Strip` objects
- `render_line(y)` uses binary search (`prefix_sum_tree.py`)
  - O(log n) turn lookup
  - O(viewport) rendering

### Hot-Reload Architecture
- Stable boundary modules (never reload): core TUI, tmux controller, forward proxy CA
- Reloadable modules: formatting, rendering, panels, actions
- Full reload on any file change (eliminates partial-reload complexity)
- Import discipline: stable modules use `import cc_dump.module` (not `from ... import`)

### Multi-Provider Support
- Provider registry (`providers.py`): Anthropic (default), OpenAI, Copilot
- Protocol families: `anthropic`, `openai`
- Proxy modes: `reverse` (HTTP), `forward` (CONNECT tunneling)
- Upstream format translation: `copilot_translate.py` (OpenAI → Anthropic format)
- Per-provider: port binding, target URL, HAR recording
