# cc-dump Architecture

A transparent HTTP proxy for monitoring Claude Code API traffic with a Textual TUI. Implements a two-stage pipeline: API data → FormattedBlock IR → Rich text rendering. See also: `HOT_RELOAD_ARCHITECTURE.md`.

## High-Level Data Flow

```
HTTP Proxy (pipeline/)
  ↓ [raw HTTP events]
Event Router (pipeline/router.py)
  ↓ [fan-out: analytics + display + HAR recording]
Event Handlers (tui/event_handlers.py) [pure functions]
  ↓ [raw events → domain state mutations]
Domain Store (app/domain_store.py) [append-only FormattedBlock trees]
  ↓ [on_turn_added / on_stream_block callbacks]
Widget Factory (tui/widget_factory.py) [TurnData + pre-rendered Strips]
  ↓ [cached turn rendering]
Rendering (tui/rendering_impl.py) [visibility rules]
  ↓ [FormattedBlock IR → Rich text]
Textual TUI (tui/app.py)
  ↓ [terminal output]
Terminal
```

## Core Abstractions

### 1. Pipeline Layer (`src/cc_dump/pipeline/`)

**Purpose**: HTTP interception, event emission, recording.

**Key modules**:
- `proxy.py` - HTTP handler, SSE parsing, request/response interception. **STABLE** — never reloaded.
- `router.py` - Event fan-out to subscribers (analytics, display, HAR).
- `event_types.py` - Type-safe event hierarchy (SSEEvent, MessageStartEvent, etc.). **STABLE** — never reloaded.
- `response_assembler.py` - Reconstructs complete SSE streams from fragments. **STABLE** — never reloaded.
- `har_recorder.py` - Writes HAR 1.2 format with complete SSE streams.
- `har_replayer.py` - Loads HAR, synthesizes events as if live.
- `copilot_translate.py` - OpenAI→Anthropic format normalization at provider boundaries.
- `forward_proxy_tls.py` - Forward proxy CONNECT tunneling + CA certificate generation. **STABLE** — holds crypto state.
- `proxy_flow.py` - Request path resolution (which provider, which transformation).
- `sentinel.py` - Request interceptor for tmux integration.

**Data flow**:
1. `ProxyHandler.do_GET/POST()` reads request, emits `RequestHeadersEvent` + `RequestBodyEvent`.
2. Forwards to upstream, reads response in chunks.
3. Emits `ResponseHeadersEvent`, then SSE events (`ResponseSSEEvent` for streaming or `ResponseNonStreamingEvent` for non-streaming).
4. On completion, emits `ResponseCompleteEvent` + `ResponseDoneEvent`.
5. `EventRouter` fans out to `QueueSubscriber` (display), `DirectSubscriber` (analytics), `DirectSubscriber` (HAR).

**Entry point**: `cli.py:main()` starts proxy servers, creates router, wires subscribers.

### 2. Core / Formatting Layer (`src/cc_dump/core/`)

**Purpose**: API JSON → FormattedBlock IR (provider-agnostic).

**Key modules**:
- `formatting_impl.py` - Converts raw API events to `FormattedBlock` tree hierarchy. Contains `ProviderRuntimeState` for request IDs, model info, usage tracking.
- `formatting.py` - Stable facade that delegates to `formatting_impl`.
- `palette.py` - Color/style definitions. Initialized early to ensure consistent theming.
- `analysis.py` - Extraction logic: token counts, tool invocations, errors, budget analysis.
- `coerce.py` - Type coercion helpers (int, bool, string normalization).
- `segmentation.py` - Text segmentation (code blocks, markdown parsing).
- `special_content.py` - Recognized patterns (URLs, code, structured data).
- `filter_registry.py` - Canonical filter/category registry shared by palette + TUI.

**Key types**:
- `FormattedBlock` - Base IR node. Subclasses: `UserMessageBlock`, `AssistantMessageBlock`, `ToolUseBlock`, `ToolResultBlock`, `TextBlock`, etc.
- `Level` (IntEnum) - Visibility: EXISTENCE=1, SUMMARY=2, FULL=3.
- `Category` - Content grouping (user, assistant, tools, system, budget, metadata, headers).
- `VisState` - Per-category visibility state: `(visible, full_detail, expanded)`.

### 3. App Layer (`src/cc_dump/app/`)

**Purpose**: Reactive state management, app-level coordination.

**Key modules**:
- `domain_store.py` - Append-only store for `FormattedBlock` trees. Reloadable but persists across hot-reload. Owns completed turns + active streaming turns.
- `view_store.py` - Reactive SnarfX store for visibility, panel state, follow mode, search state. Survives hot-reload via reconciliation.
- `settings_store.py` - User settings (themes, filters, persistence). SnarfX reactive store.
- `analytics_store.py` - SQLite-backed analytics: token counts, tool stats, model metadata. Derived from HAR files (not authoritative).
- `launch_config.py` - Saved launch configurations (tools, environment variables, tmux bindings).
- `launcher_registry.py` - Registry of discoverable launch targets.
- `tmux_controller.py` - Tmux pane/window management. **STABLE** — holds live pane references.
- `hot_reload.py` - Module classification, reload sequencing. **Stable boundary** — never reloaded.
- `error_models.py` - Error rendering view-models.
- `memory_stats.py` - Memory usage tracking for performance monitoring.

**Entry point**: `cli.py` creates stores, wires reactions, boots app.

### 4. I/O Layer (`src/cc_dump/io/`)

**Purpose**: Persistence, logging, terminal I/O.

**Key modules**:
- `sessions.py` - Recording management (list, cleanup, latest lookup).
- `settings.py` - Settings persistence (themes, filters).
- `logging_setup.py` - Centralized logger configuration. **Single enforcer** for runtime logging.
- `stderr_tee.py` - Captures stderr to log buffer (errors don't clobber TUI). **STABLE** — holds `sys.stderr` ref.
- `perf_logging.py` - Performance metrics (rendering complexity, event rate).

### 5. TUI Layer (`src/cc_dump/tui/`)

**Purpose**: Terminal user interface — rendering, input handling, panels.

**Key modules**:
- `app.py` - Textual App instance. **STABLE** — live instance, never reloaded. Coordinates all subsystems.
- `widget_factory.py` - Creates widgets from `FormattedBlock` trees. Manages virtual rendering via `TurnData` (cached strips). **Reloadable** — creates new widget instances on hot-reload.
- `rendering_impl.py` - FormattedBlock IR → Rich text, applies visibility rules (level + expanded state).
- `rendering.py` - Stable facade for rendering.
- `event_handlers.py` - Pure functions for processing proxy events into domain state mutations.
- `action_handlers.py` - User action dispatchers (search, filter, navigation).
- `search_controller.py` - Search state machine (mode, query, navigation).
- `search.py` - Search algorithm (regex, case sensitivity, incremental).
- `category_config.py` - Category metadata and default visibility.
- `action_config.py` - Action key bindings and metadata.
- `panel_registry.py` - Panel metadata (sidebar panels).
- `panel_renderers.py` - Renders specific panel types (info, keys, settings).
- `custom_footer.py` - Textual Footer widget customization.
- `stream_registry.py` - Tracks active SSE streams for display.
- `theme_controller.py` - Theme switching and palette refresh.
- `hot_reload_controller.py` - Watchfiles integration, reload triggering.
- `lifecycle_controller.py` - App startup/shutdown orchestration.
- `settings_launch_controller.py` - Settings UI + launch config UI integration.
- `location_navigation.py` - Within-session navigation (previous/next).
- `follow_mode.py` - Auto-scroll state machine (active/paused/pinned).
- `error_indicator.py` - Error badge rendering.
- `info_panel.py`, `keys_panel.py`, `settings_panel.py`, `launch_config_panel.py`, `debug_settings_panel.py` - Sidebar panel contents.
- `chip.py` - Reusable icon + label widget.
- `store_widget.py` - Mixin for widgets that read from reactive store.
- `prefix_sum_tree.py` - Fenwick tree for O(log n) line-to-turn lookup.
- `protocols.py` - Protocol definitions for widget interfaces.
- `dump_export.py` - Export conversation to file (JSON/markdown/text).
- `dump_formatting.py` - Formatting for export output.
- `input_modes.py` - Input mode metadata (key bindings by mode).
- `session_panel.py` - Sidebar panel showing sessions within session boundaries.
- `view_overrides.py` - Per-block visibility overrides (block.expanded).

## Architectural Principles

### [LAW:one-source-of-truth]
- **Provider topology** — owned by `ProxyRuntime` (one binding per provider).
- **FormattedBlock trees** — owned by `DomainStore` (append-only).
- **Reactive state** — owned by `view_store` and `settings_store` (SnarfX).
- **Recording files** — HAR is the source of truth; SQLite is a derived index.
- **Module reload order** — declared in `hot_reload.py:_RELOAD_ORDER`.

### [LAW:dataflow-not-control-flow]
- Event handling uses data-driven dispatch (event type → handler, not if/else chains).
- Status messages computed from state maps, not if/else chains.
- Binding order is fixed; variability lives in `active_specs`.
- Visibility rules applied uniformly to all blocks (no special cases per block type).

### [LAW:single-enforcer]
- **Logger config** — `io.logging_setup` only.
- **Request pipeline** — one `RequestPipeline` instance applied at every provider boundary.
- **Analytics projection** — direct subscriber updated before UI queue (prevents races).
- **Widget key consumption** — only the focused widget can consume keys.
- **SSE validation** — `pipeline.event_types.parse_sse_event()` is the sole boundary.

### [LAW:one-way-deps]
- `pipeline/` has no TUI deps.
- `core/` has no TUI deps.
- `app/` can import `pipeline/` and `core/` but not `tui/`.
- `tui/` can import all others (leaf layer).
- `tui/app.py` imports modules, not functions (safe for hot-reload).

### [LAW:locality-or-seam]
- `tui/app.py` is a thin coordinator; delegates to extracted modules: `category_config`, `action_handlers`, `search_controller`, `dump_export`, `theme_controller`, `hot_reload_controller`.
- Changes to rendering don't require editing `app.py`.
- Changes to search don't require editing `app.py`.

### [LAW:one-type-per-behavior]
- All providers share one `ProxyHandler`, parameterized by factory.
- All visibility modes use one `VisState` tuple (not three separate flags).

## Event Flow in Detail

### Live Mode (HTTP Proxy Active)

1. **Request arrival**: `proxy.py:ProxyHandler.do_GET()` reads headers + body.
2. **Event emission**: `RequestHeadersEvent(...)` + `RequestBodyEvent(...)` → event queue.
3. **Router drains**: `EventRouter._run()` pulls event, fans to subscribers.
4. **Analytics update**: `analytics_store.on_event()` (direct subscriber, updates in-memory DB).
5. **Display queue**: `QueueSubscriber.on_event()` (puts event in queue for TUI consumption).
6. **HAR recorder**: `HARRecordingSubscriber.on_event()` (writes to HAR file incrementally).
7. **TUI consumes**: `app._on_queue_events()` drains display queue periodically.
8. **Event handling**: `event_handlers.py` function processes event → domain state mutation.
9. **Domain store callback**: Fires `on_turn_added()` / `on_stream_block()`.
10. **Widget renders**: `widget_factory.py` converts `TurnData` to `Strip` objects (cached).
11. **Textual renders**: Line-by-line based on scroll viewport (virtual rendering).

### Replay Mode (HAR File)

1. **Load HAR**: `har_replayer.load_har()` parses file into request/response tuples.
2. **Synthesize events**: `har_replayer.py` yields `PipelineEvent` objects as if live.
3. **Router**: Same as live mode — events flow through subscribers identically.
4. **No HTTP**: proxy servers don't receive connections; events are synthetic.

## Key Data Structures

### FormattedBlock Hierarchy
```
FormattedBlock (base)
├── UserMessageBlock
├── AssistantMessageBlock
├── ToolUseBlock
├── ToolResultBlock
├── TextBlock
├── BudgetBlock
├── MetadataBlock
├── ErrorBlock
├── HeadersBlock
├── SystemPromptBlock
├── RequestJSONBlock
├── NewSessionBlock
└── ...
```

Each block has:
- `level: Level` — visibility tier.
- `category: Category | None` — content grouping.
- `expanded: bool | None` — override default visibility.
- `_expandable: bool` — whether it can be toggled.
- Child blocks (hierarchical composition).

### TurnData
Pre-rendered turn: turn index + block list + cached `Strip` objects + metadata.
- `turn_index: int` — position in completed turns.
- `blocks: list` — source `FormattedBlock` tree.
- `strips: list[Strip]` — pre-rendered lines (cached).
- `is_streaming: bool` — whether turn is still accumulating SSE events.

### VisState
```python
@dataclass
class VisState:
    visible: bool       # rendered at all?
    full: bool          # full detail or summary?
    expanded: bool      # over-ridden expansion state?
```

Per-category visibility state. Computed once from `view_store` keys and consumed by all renderers.

## Hot-Reload Architecture

See `HOT_RELOAD_ARCHITECTURE.md` for details. In brief:

- **Reloadable modules** — formatting, rendering, analysis, widgets. Listed in `hot_reload.py:_RELOAD_ORDER` (leaves-first dependency order).
- **Stable boundaries** — proxy, event_types, response_assembler, forward_proxy_tls, tmux_controller, stderr_tee, hot_reload.py, cli.py, app.py. Never reloaded.
- **Module import discipline** — reloadable modules use `import cc_dump.module` (not `from cc_dump.module import func`). Prevents stale references.
- **Reload trigger** — file change in watched files → `hot_reload_controller.py` → calls `hot_reload.reload_modules()` → recreates widgets.

## Initialization Sequence (`cli.py:main()`)

1. Parse CLI args.
2. Install stderr tee (capture errors before logging starts).
3. Configure logger (centralized in `io.logging_setup`).
4. Initialize color palette.
5. Handle admin commands (--list-recordings, --cleanup-recordings).
6. Load replay data if requested.
7. Build proxy runtime (one binding per active provider).
8. Create event router + subscribers (analytics, display, HAR).
9. Create stores (settings, view, domain, analytics).
10. Wire reactions in settings store.
11. Create hot-reload watcher.
12. Boot Textual app.

## Performance Characteristics

### Rendering
- **Virtual rendering**: O(log n) line-to-turn lookup via Fenwick tree prefix sums. O(viewport) actual rendering.
- **Strip caching**: Pre-rendered `Strip` objects cached per turn; invalidated on visibility change.
- **Truncation limits**: Post-render line limiting for large blocks (configurable per category).

### Event Processing
- **Queue-based fan-out**: Analytics direct subscriber (in-router thread), display queue subscriber (consumed by app periodically).
- **No backpressure**: If TUI can't keep up, events accumulate in queue (bounded by memory).

### Memory
- **Completed turns**: Configurable retention (env `CC_DUMP_MAX_COMPLETED_TURNS`, default 5000). Oldest turns pruned on overflow.
- **Streaming turns**: Active streams held in memory until finalized (request scoped).
- **Analytics DB**: SQLite with blob extraction (strings ≥512 bytes extracted to blobs table keyed by SHA256).

## Extension Points

### Adding a new provider
1. Add `ProviderSpec` to `providers.py:_PROVIDERS`.
2. Implement protocol-specific translation if needed (see `copilot_translate.py` for OpenAI→Anthropic example).
3. Proxy servers automatically created for new provider.

### Adding a new category
1. Update `tui/category_config.py:CATEGORY_CONFIG`.
2. Add visibility keys to `app/view_store.py:SCHEMA`.
3. Update `tui/rendering_impl.py` dispatch tables if custom rendering needed.
4. `VisState` computed automatically from keys.

### Adding a new sidebar panel
1. Create module in `tui/` with panel content widget.
2. Register in `tui/panel_registry.py:PANELS`.
3. Wire into app's `compose()` if visible by default.

## Testing

- **Unit tests** — test pure functions in isolation (formatting, analysis, rendering).
- **Integration tests** — mock proxy events, verify domain store mutations + rendered output.
- **E2E tests** — replay real HAR files, verify TUI matches expected state.
- **Fixture-based** — class-scoped fixtures share proxy process across tests in a class for speed.

See `tests/README.md` for test suite details.
