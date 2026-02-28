# Copilot Instructions

cc-dump is a transparent HTTP proxy for monitoring Claude Code API traffic. It provides a real-time Textual TUI with HAR recording/replay, system prompt diff tracking, and token/cost analytics. Python 3.10+.

## Commands

```bash
# Run
just run                            # live proxy mode
just web                            # browser mode via textual-serve

# Test
just test                           # parallel (pytest -n auto)
just test-seq                       # sequential
uv run pytest tests/test_foo.py -v  # single file
uv run pytest -k "test_name"        # single test

# Lint & format
just lint                           # ruff check + mypy
just fmt                            # ruff format

# Install
just install                        # uv tool install -e .
just reinstall                      # after structural changes
```

CI runs specific test files, not the full suite — see `.github/workflows/test.yml` for the exact list.

## Architecture

**Two-stage pipeline:** API data → `FormattedBlock` IR (`core/formatting.py`) → Rich Text (`tui/rendering.py`). Formatting is rendering-backend-agnostic.

**Event flow:**
```
pipeline/proxy.py  (HTTP intercept, emits events)
  → pipeline/router.py  (fan-out: QueueSubscriber for TUI, DirectSubscriber for analytics + HAR)
    → tui/event_handlers.py  (drains queue, calls formatting)
      → core/formatting.py  (API JSON → FormattedBlock dataclasses)
        → tui/widget_factory.py  (stores TurnData with pre-rendered strips)
          → tui/rendering.py  (FormattedBlock → Rich Text)
```

**Package layout:**
- `core/` — Pure data: formatting IR, analysis, token counting, palette
- `pipeline/` — HTTP proxy, event types, routing, HAR record/replay
- `tui/` — Textual app, rendering, widgets, input modes, panels
- `app/` — Application state: settings, analytics DB, hot-reload, view store, launch configs
- `ai/` — Side-channel AI enrichment (spawns `claude -p` subprocess)
- `io/` — Logging, sessions, settings persistence

**Key types:**
- `FormattedBlock` hierarchy (`core/formatting.py`) — the IR between formatting and rendering. Has `Level` (EXISTENCE=1, SUMMARY=2, FULL=3), `Category`, `expanded` fields.
- `TurnData` (`tui/widget_factory.py`) — completed turn: blocks + pre-rendered Rich strips
- `EventRouter` (`pipeline/router.py`) — fan-out with pluggable subscribers
- Event dataclasses (`pipeline/event_types.py`) — proxy→router communication

**Virtual rendering:** `ConversationView` uses Textual's Line API with binary search over turns — O(log n) lookup, O(viewport) rendering.

**Recording/replay:** HAR files are the source of truth. SQLite (`app/analytics_store.py`) is a derived index with content-addressed blob storage. The DB can be rebuilt by replaying HAR files.

## Provider System

Provider specs (`providers.py`) use `protocol_family` ("anthropic" | "openai") to dispatch formatters and assemblers. Multiple providers can share the same protocol family (e.g., copilot and openai both use "openai").

## Hot-Reload System

Any file change triggers full module reload + widget replacement.

**Critical rule:** Stable boundary modules must use `import cc_dump.module` — never `from cc_dump.module import func`. Direct imports create stale references that won't update on reload.

Check `app/hot_reload.py` for `_RELOAD_ORDER` (reloadable modules in dependency order), `_EXCLUDED_FILES` (stable boundaries), and `_EXCLUDED_MODULES` (stable TUI modules). When adding new modules, classify them accordingly.

## 3-Level Visibility System

Each content category (user, assistant, tools, system, budget, metadata, headers) has 3 levels × 2 states (collapsed/expanded). Rendering uses a two-tier dispatch: state-specific renderers keyed by `(block type, level, expanded)` with fallback to generic renderers + truncation limits.

## Conventions

- `FormattedBlock` subclasses use `@dataclass` with `field()` for mutable defaults
- Per-module loggers: `logger = logging.getLogger(__name__)` — no print/stderr
- Use `truststore.SSLContext` instead of `ssl.create_default_context()` for OS trust store support
- Render key tuples `(width, search_revision, theme_revision, overrides_revision)` gate re-renders — call `mark_overrides_changed()` after mutating `ViewOverrides`
- Filter revision tracking: per-turn `_filter_revision` field with global `_active_filter_revision` counter detects stale filter state
- Coalesce offset recalculations via `_schedule_deferred_offset_recalc` / `_flush_deferred_offset_recalc`
- OpenAI models use 50% discount for cached input tokens

## SnarfX

`snarfx/` is a **separate git repository** (MobX-inspired reactive state for Python). Do not `git add` snarfx files to this repo — use `git -C snarfx` for all snarfx git operations. In CI, snarfx is provided via `.github/create-snarfx-stub.py`.
