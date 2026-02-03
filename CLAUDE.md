# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

cc-dump is a transparent HTTP proxy for monitoring Claude Code API traffic. It intercepts Anthropic API requests, tracks system prompt changes with diffs, and provides a real-time Textual TUI with HAR recording/replay capabilities. Python 3.10+, single production dependency (`textual`). See [PROJECT_SPEC.md](PROJECT_SPEC.md) for goals and [ARCHITECTURE.md](ARCHITECTURE.md) for system design.

## Commands

```bash
# Run (live proxy mode)
just run                          # or: uv run cc-dump [--port PORT] [--target URL]

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
# ANTHROPIC_BASE_URL=http://127.0.0.1:3344 claude
```

## Architecture

**Two-stage pipeline:** API data → FormattedBlock IR (`formatting.py`) → Rich Text (`tui/rendering.py`). This separation means formatting logic is rendering-backend-agnostic.

**Event flow:**
```
proxy.py (HTTP intercept, emits events)
  → router.py (fan-out: QueueSubscriber for TUI, DirectSubscriber for SQLite, DirectSubscriber for HAR)
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

**Database:** SQLite with content-addressed blob storage. Large strings (≥512 bytes) are extracted to a `blobs` table keyed by SHA256, replaced with `{"__blob__": hash}` references. DB is a derived index — token counts and tool statistics are queried from it directly. In principle, SQLite can be rebuilt by replaying HAR files.

## Hot-Reload System

See `HOT_RELOAD_ARCHITECTURE.md` for full details. The critical rule:

**Stable boundary modules** (`proxy.py`, `cli.py`, `tui/app.py`, `tui/widgets.py`, `hot_reload.py`, `har_recorder.py`, `har_replayer.py`, `sessions.py`) must use `import cc_dump.module` — never `from cc_dump.module import func`. Direct imports create stale references that won't update on reload.

**Reloadable modules** (`formatting.py`, `tui/rendering.py`, `tui/widget_factory.py`, `tui/event_handlers.py`, `tui/panel_renderers.py`, `colors.py`, `analysis.py`, `palette.py`, `tui/protocols.py`, `tui/custom_footer.py`) can be safely reloaded in dependency order.

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
