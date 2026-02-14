# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

cc-dump is a transparent HTTP proxy for monitoring Claude Code API traffic. It intercepts Anthropic API requests, tracks system prompt changes with diffs, and provides a real-time Textual TUI with HAR recording/replay capabilities. Python 3.10+, production dependencies: `textual`, `textual-serve`, `tiktoken`. See [PROJECT_SPEC.md](PROJECT_SPEC.md) for goals and [ARCHITECTURE.md](ARCHITECTURE.md) for system design.

## Textual Framework Reference

We use the Textual TUI framework. Reference documentation is in `dev-docs/textual-docs/`:

**Always load first:** @dev-docs/textual-docs/CC_DUMP_USAGE.md - Summary of Textual APIs we actually use in cc-dump

**Full reference:** @dev-docs/textual-docs/INDEX.md - Index of all 42 granular documentation files organized by category (core APIs, widgets, support modules)

When working on TUI code, consult CC_DUMP_USAGE.md first to see what we use, then load specific files from the index as needed. Files are small (2-93KB) and focused on single concepts.

## Commands

```bash
# Run (live proxy mode)
just run                          # or: uv run cc-dump [--port PORT] [--target URL]

# Run in browser via textual-serve
just web                          # launches at http://localhost:8000
# or: cc-dump-serve                # standalone command

# Recording and replay
cc-dump --list                    # list available recordings
cc-dump --replay <path>           # replay a HAR file
cc-dump --replay latest           # replay most recent recording
cc-dump --no-record               # disable recording (live mode)
cc-dump --record <path>           # custom recording path

# Test
uv run pytest                     # all tests
uv run pytest tests/test_foo.py -v  # single file
uv run pytest -k "test_name"      # single test

# Lint & format
just lint                         # uvx ruff check src/
just fmt                          # uvx ruff format src/

# Install as tool
just install                      # uv tool install -e .
just reinstall                    # after structural changes

# Run with Claude Code (reverse proxy mode)
# cc-dump prints the assigned port on startup (OS-assigned by default)
# ANTHROPIC_BASE_URL=http://127.0.0.1:<PORT> claude
```

## Architecture

**Two-stage pipeline:** API data → FormattedBlock IR (`formatting.py`) → Rich Text (`tui/rendering.py`). This separation means formatting logic is rendering-backend-agnostic.

**Event flow:**
```
proxy.py (HTTP intercept, emits events)
  → router.py (fan-out: QueueSubscriber for TUI, DirectSubscriber for analytics, DirectSubscriber for HAR)
    → event_handlers.py (drains queue, calls formatting)
      → formatting.py (API JSON → FormattedBlock dataclasses)
        → widget_factory.py (stores TurnData with pre-rendered strips)
          → tui/rendering.py (FormattedBlock → Rich Text for display)
```

**Recording and replay:**
- **Live mode:** `har_recorder.py` subscribes to events, accumulates SSE streams, reconstructs complete messages, writes HAR 1.2 format
- **Replay mode:** `har_replayer.py` loads HAR, synthesizes events, feeds to same router/pipeline as live mode
- **Key principle:** HAR files are the source of truth for events, SQLite is a derived index for analytics

**Virtual rendering:** `ConversationView` uses Textual's Line API. Completed turns are stored as `TurnData` (blocks + pre-rendered strips). `render_line(y)` uses binary search over turns — O(log n) lookup, O(viewport) rendering.

**Database:** `analytics_store.py` — SQLite with content-addressed blob storage. Large strings (≥512 bytes) are extracted to a `blobs` table keyed by SHA256, replaced with `{"__blob__": hash}` references. DB is a derived index — token counts and tool statistics are queried from it directly. In principle, SQLite can be rebuilt by replaying HAR files.

## Hot-Reload System

See `HOT_RELOAD_ARCHITECTURE.md` for full details. The critical rule:

**Stable boundary modules** must use `import cc_dump.module` — never `from cc_dump.module import func`. Direct imports create stale references that won't update on reload.

**Any file change triggers full reload + widget replacement.** This is intentional — the reload is fast and eliminates partial-reload complexity.

To discover which modules are stable vs reloadable, check `hot_reload.py`:
```bash
grep -A 20 '_RELOAD_ORDER' src/cc_dump/hot_reload.py    # reloadable modules, in dependency order
grep -A 10 '_EXCLUDED_FILES' src/cc_dump/hot_reload.py   # stable boundaries (never reload)
grep -A 10 '_EXCLUDED_MODULES' src/cc_dump/hot_reload.py # stable TUI modules (never reload)
```

When adding new modules, classify them as stable or reloadable and follow the corresponding import pattern.

## Key Types

- `FormattedBlock` hierarchy in `formatting.py` — the IR between formatting and rendering. Discover subclasses: `grep 'class.*FormattedBlock' src/cc_dump/formatting.py`
  - `Level` enum (IntEnum): EXISTENCE=1, SUMMARY=2, FULL=3 — visibility levels
  - `Category` enum — content groupings. Discover values: `grep 'class Category' -A 20 src/cc_dump/formatting.py`
  - `expanded: bool | None` field — per-block expansion override (None = use level default)
  - `category: Category | None` field — category assignment (None = use BLOCK_CATEGORY static mapping)
- `TurnData` in `widget_factory.py` — completed turn: list of blocks + pre-rendered Rich strips.
- `EventRouter` in `router.py` — fan-out with pluggable `QueueSubscriber` / `DirectSubscriber`.
- Event types in `event_types.py` — dataclasses for proxy→router communication. Discover: `grep 'class.*:' src/cc_dump/event_types.py`

## 3-Level Visibility System

**User-facing docs:** See [docs/VISIBILITY_SYSTEM.md](docs/VISIBILITY_SYSTEM.md) and [docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)

**Architecture:** Each category has 3 levels (EXISTENCE/SUMMARY/FULL) × 2 states (collapsed/expanded) = 6 visual representations.

**Rendering pipeline:** `rendering.py:render_turn_to_strips()` is the entry point. Key concepts:
1. **Two-tier dispatch:** state-specific renderers (keyed by block type + level + expanded) with fallback to generic block renderers + truncation limits
2. **Category resolution:** `block.category` field, falling back to static mapping
3. **Visibility resolution:** returns `(level, expanded)` tuple per block
4. **Generic truncation:** post-render line limiting with collapse indicators for truncated blocks
5. **Expandability:** `block._expandable` flag set when block exceeds line limit (enables click-to-expand)

Discover the dispatch tables: `grep 'BLOCK_.*RENDERERS\|TRUNCATION_LIMITS\|BLOCK_CATEGORY' src/cc_dump/tui/rendering.py`

**Tool pre-pass:** At tools level ≤ SUMMARY, `collapse_tool_runs()` creates `ToolUseSummaryBlock` from consecutive tool use/result pairs.

**Click behavior:** `on_click()` in `widget_factory.py` toggles `block.expanded` within current level (only if `block._expandable`).

**Keyboard cycling:** `action_cycle_*()` in `app.py` cycles reactive `vis_*` (1→2→3→1) and clears per-block overrides via `_clear_overrides()`.

**Key mappings:**
- Number keys: `1` user, `2` assistant, `3` tools, `4` system, `5` budget, `6` metadata, `7` headers
- Shift+number toggles detail (e.g., `!` for user detail toggle)
- Panels: `.` cycle panel, `,` panel mode, `0` follow mode
- Vim navigation: `g`/`G` top/bottom, `j`/`k` line scroll, `h`/`l` column scroll, `ctrl+d`/`ctrl+u` half-page, `ctrl+f`/`ctrl+b` full-page
- Default levels: headers/metadata/budget=EXISTENCE, user/assistant=FULL, tools/system=SUMMARY

## Issue Tracking

Uses `bd` (beads) CLI. Always pass `--json` flag. Issues in `.beads/issues.jsonl` — commit with code changes.

```bash
bd ready --json          # find unblocked work
bd update <id> --status in_progress --json
bd close <id> --reason "done" --json
```

## Session Completion

Work is not complete until `git push` succeeds. Mandatory: run tests, update issue status, `bd sync`, push, verify with `git status`.
