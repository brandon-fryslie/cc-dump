# cc-dump Directory Structure

```
/Users/bmf/code/cc-dump/
├── src/cc_dump/                      # Main source tree
│   ├── __init__.py
│   ├── __main__.py                   # Entry: python -m cc_dump
│   ├── cli.py                        # [STABLE] CLI entry point, startup orchestration
│   ├── providers.py                  # [ONE-SOURCE-OF-TRUTH] Provider registry + metadata
│   ├── cli_presentation.py           # CLI output formatting
│   ├── serve.py                      # textual-serve integration
│   │
│   ├── pipeline/                     # [STABLE BOUNDARY] HTTP proxy + event emission
│   │   ├── __init__.py
│   │   ├── proxy.py                  # [STABLE] HTTP handler, SSE parsing, request/response interception
│   │   ├── proxy_flow.py             # Request path resolution (provider routing)
│   │   ├── response_assembler.py     # [STABLE] Reconstruct complete SSE from fragments
│   │   ├── event_types.py            # [STABLE] Type-safe event hierarchy (base + 13 subclasses)
│   │   ├── router.py                 # Event fan-out (QueueSubscriber, DirectSubscriber)
│   │   ├── har_recorder.py           # Writes HAR 1.2 format (includes reconstructed SSE)
│   │   ├── har_replayer.py           # Load HAR, synthesize events as if live
│   │   ├── copilot_translate.py      # OpenAI ↔ Anthropic format translation at provider boundary
│   │   ├── forward_proxy_tls.py      # [STABLE] CONNECT tunnels + CA cert generation
│   │   └── sentinel.py               # Request interceptor (tmux integration marker)
│   │
│   ├── core/                         # [STABLE BOUNDARY] Data → FormattedBlock IR
│   │   ├── __init__.py
│   │   ├── formatting_impl.py        # [RELOADABLE] Raw events → FormattedBlock tree + ProviderRuntimeState
│   │   ├── formatting.py             # [FACADE] Stable import boundary (delegates to formatting_impl)
│   │   ├── palette.py                # [RELOADABLE] Color/style definitions, initialized early
│   │   ├── analysis.py               # [RELOADABLE] Token counts, tool invocation extraction
│   │   ├── filter_registry.py        # [RELOADABLE] Category + filter canonical registry
│   │   ├── coerce.py                 # [RELOADABLE] Type coercion helpers
│   │   ├── segmentation.py           # [RELOADABLE] Text segmentation (code blocks, markdown)
│   │   └── special_content.py        # [RELOADABLE] Pattern recognition (URLs, code, structured)
│   │
│   ├── app/                          # Reactive state, coordination
│   │   ├── __init__.py
│   │   ├── domain_store.py           # [RELOADABLE] Append-only FormattedBlock trees (persists across reload)
│   │   ├── view_store.py             # [RELOADABLE] SnarfX reactive store (visibility, panels, search, follow)
│   │   ├── settings_store.py         # [RELOADABLE] SnarfX reactive store (user settings, persistence)
│   │   ├── analytics_store.py        # SQLite-backed analytics (derived from HAR, not authoritative)
│   │   ├── launch_config.py          # [RELOADABLE] Saved launch configs (tools, env vars, tmux)
│   │   ├── launcher_registry.py      # [RELOADABLE] Discoverable launch targets
│   │   ├── hot_reload.py             # [STABLE] Module classification, reload sequencing
│   │   ├── tmux_controller.py        # [STABLE] Tmux pane/window management (holds live refs)
│   │   ├── error_models.py           # [RELOADABLE] Error rendering view-models
│   │   └── memory_stats.py           # Performance monitoring (memory usage)
│   │
│   ├── io/                           # I/O, persistence, logging
│   │   ├── __init__.py
│   │   ├── logging_setup.py          # [SINGLE-ENFORCER] Centralized logger config
│   │   ├── settings.py               # Settings persistence (JSON, YAML, etc.)
│   │   ├── sessions.py               # Recording management (list, cleanup, latest lookup)
│   │   ├── stderr_tee.py             # [STABLE] Stderr capture (holds sys.stderr ref)
│   │   └── perf_logging.py           # Performance metrics (rendering complexity, event rate)
│   │
│   ├── tui/                          # [LEAF LAYER] Terminal UI
│   │   ├── __init__.py
│   │   │
│   │   ├── app.py                    # [STABLE] Textual App instance, global coordinator (never reloaded)
│   │   ├── action_handlers.py        # [RELOADABLE] User action dispatchers (search, filter, nav)
│   │   ├── action_config.py          # [RELOADABLE] Action metadata + key bindings
│   │   ├── category_config.py        # [RELOADABLE] Category metadata + default visibility
│   │   ├── protocols.py              # Protocol definitions (widget interfaces)
│   │   │
│   │   ├── rendering_impl.py         # [RELOADABLE] FormattedBlock → Rich text (visibility rules)
│   │   ├── rendering.py              # [FACADE] Stable import boundary (delegates to rendering_impl)
│   │   ├── widget_factory.py         # [RELOADABLE] Creates widgets from FormattedBlocks (TurnData + Strips)
│   │   ├── event_handlers.py         # [RELOADABLE] Pure functions: proxy events → domain state mutations
│   │   ├── stream_registry.py        # [RELOADABLE] Tracks active SSE streams
│   │   ├── search.py                 # [RELOADABLE] Search algorithm (regex, incremental)
│   │   ├── search_controller.py      # [RELOADABLE] Search state machine + navigation
│   │   ├── follow_mode.py            # [RELOADABLE] Auto-scroll state machine (active/paused/pinned)
│   │   ├── location_navigation.py    # Within-session prev/next navigation
│   │   ├── panel_registry.py         # [RELOADABLE] Panel metadata
│   │   ├── panel_renderers.py        # [RELOADABLE] Render specific panel types
│   │   ├── dump_export.py            # [RELOADABLE] Export conversation (JSON/markdown/text)
│   │   ├── dump_formatting.py        # [RELOADABLE] Export formatting
│   │   ├── error_indicator.py        # [RELOADABLE] Error badge rendering
│   │   ├── theme_controller.py       # [RELOADABLE] Theme switching + palette refresh
│   │   ├── hot_reload_controller.py  # Watchfiles integration, reload triggering
│   │   ├── lifecycle_controller.py   # [RELOADABLE] Startup/shutdown orchestration
│   │   ├── settings_launch_controller.py # [RELOADABLE] Settings + launch config UI
│   │   ├── view_overrides.py         # [RELOADABLE] Per-block visibility overrides
│   │   ├── prefix_sum_tree.py        # [RELOADABLE] Fenwick tree (O(log n) line-to-turn lookup)
│   │   ├── input_modes.py            # [RELOADABLE] Input mode metadata + key bindings
│   │   │
│   │   ├── custom_footer.py          # [RELOADABLE] Textual Footer customization
│   │   ├── chip.py                   # [RELOADABLE] Icon + label widget
│   │   ├── store_widget.py           # [RELOADABLE] Mixin for reactive store-reading widgets
│   │   │
│   │   ├── info_panel.py             # [RELOADABLE] Sidebar info panel
│   │   ├── keys_panel.py             # [RELOADABLE] Sidebar keys panel
│   │   ├── settings_panel.py         # [RELOADABLE] Sidebar settings panel
│   │   ├── launch_config_panel.py    # [RELOADABLE] Sidebar launch config panel
│   │   ├── session_panel.py          # [RELOADABLE] Sidebar session boundaries panel
│   │   ├── debug_settings_panel.py   # [RELOADABLE] Sidebar debug settings panel
│   │   └── session_panel.py          # [RELOADABLE] Session navigation panel
│   │
│   ├── experiments/                  # Experimental features (not in main flow)
│   │   ├── __init__.py
│   │   ├── memory_soak.py            # Memory stress test
│   │   ├── perf_metrics.py           # Performance benchmark
│   │   └── subagent_enrichment.py    # Subagent metadata extraction
│   │
│   └── proxies/                      # Provider-specific proxy logic (optional)
│       ├── __init__.py
│       └── copilot/                  # GitHub Copilot integration
│           └── __init__.py
│
├── tests/                            # Test suite
│   ├── __init__.py
│   ├── conftest.py                   # Pytest fixtures (class_proc, settle, wait_for_content, etc.)
│   ├── README.md                     # Test architecture notes
│   │
│   ├── test_*.py                     # Unit/integration tests
│   ├── unit/                         # Unit test subdirectories
│   ├── integration/
│   └── e2e/
│
├── spec/                             # Functional specifications
│   ├── INDEX.md                      # Index of all specs
│   ├── cli.md                        # CLI argument structure
│   ├── proxy.md                      # Proxy behavior + event types
│   ├── recording.md                  # HAR recording + replay
│   ├── formatting.md                 # FormattedBlock hierarchy + rules
│   ├── rendering.md                  # Rendering algorithm (visibility, truncation)
│   ├── hot-reload.md                 # Hot-reload mechanics
│   ├── visibility.md                 # 3-level visibility system (EXISTENCE/SUMMARY/FULL)
│   ├── navigation.md                 # Keyboard navigation (vim keys, panels, search)
│   ├── filters.md                    # Filter/category definitions
│   ├── panels.md                     # Sidebar panel definitions
│   ├── search.md                     # Search modes + behavior
│   ├── sessions.md                   # Session handling + boundaries
│   ├── themes.md                     # Theme + palette system
│   ├── analytics.md                  # Analytics DB schema + derivation
│   ├── errors.md                     # Error handling + display
│   └── export.md                     # Export formats (JSON, markdown, text)
│
├── dev-docs/                         # Developer documentation
│   ├── textual-docs/                 # Granular Textual framework reference (42 files, 902KB)
│   │   ├── INDEX.md                  # Index of all docs
│   │   ├── CC_DUMP_USAGE.md          # Textual APIs we actually use
│   │   ├── core/                     # App, binding, reactive, etc.
│   │   ├── widgets/                  # Button, checkbox, data_table, etc.
│   │   └── support/                  # CSS, geometry, styling, utils
│   │
│   ├── HOT_RELOAD_ARCHITECTURE.md    # Detailed hot-reload system design
│   ├── VISIBILITY_SYSTEM.md          # 3-level visibility + UI behavior
│   └── QUICK_REFERENCE.md            # Frequently-used operations
│
├── docs/                             # User-facing documentation
│   ├── VISIBILITY_SYSTEM.md          # User guide to visibility levels
│   └── QUICK_REFERENCE.md            # Quick reference for users
│
├── scripts/                          # Build/automation scripts
├── benchmarks/                       # Performance benchmarks
├── stubs/                            # Type stubs (not auto-generated)
├── .planning/                        # Planning documents
│   └── codebase/                     # This directory
│       ├── ARCHITECTURE.md           # [THIS FILE] High-level system design
│       └── STRUCTURE.md              # [THIS FILE] Directory layout + key locations
│
├── CLAUDE.md                         # Project instructions (checked into repo)
├── .claude/                          # User's global instructions (git-ignored)
├── pyproject.toml                    # Python package metadata
├── uv.lock                           # Locked dependency versions
├── justfile                          # Build recipes (just run, just test, etc.)
└── README.md                         # Project README
```

## Key File Locations

### Entry Points
- `src/cc_dump/__main__.py` — Python -m execution.
- `src/cc_dump/cli.py` — Main entry point (argparse, startup orchestration).
- `src/cc_dump/tui/app.py` — Textual App (never hot-reloaded).

### Core Data Structures
- `src/cc_dump/pipeline/event_types.py` — Event hierarchy (SSEEvent, MessageStartEvent, etc.). **STABLE**, never reloaded.
- `src/cc_dump/core/formatting_impl.py` — FormattedBlock hierarchy definitions. **Reloadable**.

### State Management
- `src/cc_dump/app/domain_store.py` — Append-only FormattedBlock trees. **Reloadable but persists across reload**.
- `src/cc_dump/app/view_store.py` — Reactive visibility state (SnarfX). **Reloadable, survives via reconcile**.
- `src/cc_dump/app/settings_store.py` — User settings (SnarfX). **Reloadable, persisted to disk**.

### HTTP Proxy
- `src/cc_dump/pipeline/proxy.py` — HTTP handler. **STABLE**, never reloaded.
- `src/cc_dump/pipeline/router.py` — Event fan-out.
- `src/cc_dump/pipeline/har_recorder.py` — HAR file writer.
- `src/cc_dump/pipeline/har_replayer.py` — HAR replay.

### Rendering Pipeline
- `src/cc_dump/core/formatting_impl.py` — API JSON → FormattedBlock IR. **Reloadable**.
- `src/cc_dump/tui/rendering_impl.py` — FormattedBlock → Rich text. **Reloadable**.
- `src/cc_dump/tui/widget_factory.py` — TurnData + Strip caching. **Reloadable**.

### Configuration & Metadata
- `src/cc_dump/providers.py` — Provider registry (ONE-SOURCE-OF-TRUTH).
- `src/cc_dump/tui/category_config.py` — Category definitions. **Reloadable**.
- `src/cc_dump/tui/action_config.py` — Action metadata. **Reloadable**.
- `src/cc_dump/tui/panel_registry.py` — Panel definitions. **Reloadable**.

### Hot-Reload System
- `src/cc_dump/app/hot_reload.py` — Module classification, reload sequencing. **STABLE**.
- `src/cc_dump/tui/hot_reload_controller.py` — Watchfiles integration, reload triggering.
- See `dev-docs/HOT_RELOAD_ARCHITECTURE.md` for detailed design.

### Specifications
- `spec/INDEX.md` — Master index of all specs.
- `spec/formatting.md` — FormattedBlock rules.
- `spec/rendering.md` — Rendering algorithm.
- `spec/hot-reload.md` — Hot-reload mechanics.
- `spec/visibility.md` — 3-level visibility system.

### Tests
- `tests/conftest.py` — Pytest fixtures (class_proc, settle, wait_for_content).
- `tests/test_*.py` — Individual test modules.
- `tests/README.md` — Test architecture.

## Naming Conventions

### Module Organization
- **Facade modules** — `*.py` imports from `*_impl.py` via `__getattr__`. Examples: `formatting.py` → `formatting_impl.py`, `rendering.py` → `rendering_impl.py`. Stable import boundaries for hot-reload.
- **Controller modules** — `*_controller.py` coordinates state/logic. Examples: `hot_reload_controller.py`, `lifecycle_controller.py`, `theme_controller.py`.
- **Config modules** — `*_config.py` or `*_registry.py` hold metadata/configuration. Examples: `category_config.py`, `action_config.py`, `panel_registry.py`, `launcher_registry.py`.
- **Panel modules** — `*_panel.py` are sidebar panel contents. Examples: `info_panel.py`, `keys_panel.py`, `settings_panel.py`.
- **Store modules** — `*_store.py` hold application state. Examples: `domain_store.py`, `view_store.py`, `settings_store.py`, `analytics_store.py`.

### Class Naming
- **FormattedBlock subclasses** — `*Block`. Examples: `UserMessageBlock`, `AssistantMessageBlock`, `ToolUseBlock`, `TextBlock`, `BudgetBlock`, `MetadataBlock`.
- **Event classes** — `*Event`. Examples: `RequestHeadersEvent`, `ResponseSSEEvent`, `MessageStartEvent`.
- **State dataclasses** — `*State` or `*Store`. Examples: `ProviderRuntimeState`, `TmuxState`.
- **Controllers** — `*Controller`. Examples: `TmuxController`, `EventRouter`.

### Function Naming
- **Pure functions** — `format_*`, `render_*`, `parse_*`, `extract_*`, etc. Examples: `parse_sse_event()`, `extract_tool_calls()`.
- **Side-effectful functions** — Often methods on controller/store objects.
- **Underscore prefix** — Private functions (module-internal).
- **Handler methods** — `on_*`. Examples: `on_event()`, `on_turn_added()`.

### Type Aliases
- `JsonDict` — `dict[str, object]` (JSON-parsed data).
- `ProtocolFamily` — `Literal["anthropic", "openai"]`.
- `ProxyMode` — `Literal["reverse", "forward"]`.
- `UpstreamFormat` — `Literal["anthropic", "openai-chat", "openai-responses"]`.

## Module Dependencies (Layered)

```
Leaf Layer (TUI)
  tui/ → imports from everything below

Application Layer
  app/ → imports pipeline, core, io

Core Transformation Layer
  core/ → imports io (logging only)

Pipeline/I/O Layer
  pipeline/ (no TUI deps)
  io/ (no TUI deps)
```

**Key constraint**: No circular dependencies. One-way flow from leaves (TUI) inward to stable boundaries (pipeline, io).

## Testing Structure

- **Unit tests** — Pure functions isolated (formatting, rendering, analysis).
- **Integration tests** — Mocked proxy events → domain store → widget renders.
- **E2E tests** — Real HAR files → replay → verify output.
- **Fixtures** — Class-scoped for test speed (share process across tests in class).
  - `class_proc` / `class_proc_with_port` — Shared proxy process.
  - `settle()` — Wait for startup readiness.
  - `wait_for_content()` — Wait for specific TUI content.

See `tests/README.md` for full details.

## Performance Considerations

### Memory
- **Completed turns**: Retention limit (env `CC_DUMP_MAX_COMPLETED_TURNS`, default 5000).
- **Streaming turns**: Garbage-collected when finalized.
- **Caches**: LRU cache on Strip objects (Textual built-in).
- **Analytics DB**: Blob extraction (strings ≥512 bytes → separate table).

### CPU
- **Virtual rendering**: O(log n) line lookup, O(viewport) rendering.
- **Event fan-out**: Direct subscribers (analytics) run in router thread; queue subscriber (display) consumed by app thread periodically.
- **Reload**: Full reload + widget replacement (intentional — eliminates partial-reload complexity).

### I/O
- **HAR recording**: Incremental writes, one file per provider per session.
- **Replay**: Lazy load (reads on demand, not all at once).
- **Analytics**: SQLite with indexing for common queries.

## Stability Markers

Files marked **[STABLE]** are never hot-reloaded and are safe for `from` imports everywhere:
- `pipeline/proxy.py`
- `pipeline/event_types.py`
- `pipeline/response_assembler.py`
- `pipeline/forward_proxy_tls.py`
- `app/hot_reload.py`
- `app/tmux_controller.py`
- `io/stderr_tee.py`
- `tui/app.py`
- `cli.py`

**Reloadable modules** use `import cc_dump.module` (not `from` imports) and are listed in `app/hot_reload.py:_RELOAD_ORDER` in dependency order (leaves first).
