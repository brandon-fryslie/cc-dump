# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

cc-dump is a transparent HTTP proxy for monitoring Claude Code API traffic. It intercepts Anthropic API requests, tracks system prompt changes with diffs, and provides a real-time Textual TUI. Python 3.10+, single production dependency (`textual`).

## Commands

```bash
# Run
just run                          # or: uv run cc-dump [--port PORT] [--target URL]

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
```

## Architecture

**Two-stage pipeline:** API data → FormattedBlock IR (`formatting.py`) → Rich Text (`tui/rendering.py`). This separation means formatting logic is rendering-backend-agnostic.

**Event flow:**
```
proxy.py (HTTP intercept, emits events)
  → router.py (fan-out: QueueSubscriber for TUI, DirectSubscriber for SQLite)
    → event_handlers.py (drains queue, calls formatting)
      → formatting.py (API JSON → FormattedBlock dataclasses)
        → widget_factory.py (stores TurnData with pre-rendered strips)
          → tui/rendering.py (FormattedBlock → Rich Text for display)
```

**Virtual rendering:** `ConversationView` uses Textual's Line API. Completed turns are stored as `TurnData` (blocks + pre-rendered strips). `render_line(y)` uses binary search over turns — O(log n) lookup, O(viewport) rendering.

**Database:** SQLite with content-addressed blob storage. Large strings (≥512 bytes) are extracted to a `blobs` table keyed by SHA256, replaced with `{"__blob__": hash}` references. DB is the single source of truth for token counts — panels query it directly, no in-memory accumulation.

## Hot-Reload System

See `HOT_RELOAD_ARCHITECTURE.md` for full details. The critical rule:

**Stable boundary modules** (`proxy.py`, `cli.py`, `tui/app.py`, `tui/widgets.py`, `hot_reload.py`) must use `import cc_dump.module` — never `from cc_dump.module import func`. Direct imports create stale references that won't update on reload.

**Reloadable modules** (`formatting.py`, `tui/rendering.py`, `tui/widget_factory.py`, `tui/event_handlers.py`, `tui/panel_renderers.py`, `colors.py`, `analysis.py`, `tui/protocols.py`) can be safely reloaded in dependency order.

When adding new modules, classify them as stable or reloadable and follow the corresponding import pattern.

## Key Types

- `FormattedBlock` hierarchy in `formatting.py` — the IR between formatting and rendering. Subclasses: `HeaderBlock`, `MetadataBlock`, `TrackedContentBlock`, `ToolUseBlock`, `ToolResultBlock`, `TextDeltaBlock`, `StreamInfoBlock`, `TurnBudgetBlock`, etc.
- `TurnData` in `widget_factory.py` — completed turn: list of blocks + pre-rendered Rich strips.
- `EventRouter` in `router.py` — fan-out with pluggable `QueueSubscriber` / `DirectSubscriber`.

## Issue Tracking

Uses `bd` (beads) CLI. Always pass `--json` flag. Issues in `.beads/issues.jsonl` — commit with code changes.

```bash
bd ready --json          # find unblocked work
bd update <id> --status in_progress --json
bd close <id> --reason "done" --json
```

## Session Completion

Work is not complete until `git push` succeeds. Mandatory: run tests, update issue status, `bd sync`, push, verify with `git status`.
