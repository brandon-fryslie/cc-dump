# Evaluation: Hot-Reload for TUI Mode (Remove Legacy Mode)

## Current State

The project has two code paths in `cli.py`:
1. **`--no-tui` (legacy)**: A main-thread consumer loop that calls `_check_reload()` + `display.handle()`
2. **TUI (default)**: Launches `CcDumpApp` which drains events from a queue subscriber

The hot-reload mechanism (`_check_reload()`) only works in the legacy `--no-tui` path. The TUI mode has **zero hot-reload support**.

## Problem Statement

Per the original architecture spec (`.agent_planning/hot-reload/`), the design intent is:
- **Proxy = stable boundary** (never reloaded)
- **Everything else = hot-reloadable** (display, formatting, analysis, TUI)

The `--no-tui` flag was an engineering quality lapse:
- It introduced a second display mode that violates "one type per behavior"
- It maintains dead code (`display.py`, `formatting_ansi.py`) that duplicates TUI rendering
- The hot-reload mechanism was never ported to TUI mode

## What Must Change

### Sprint 1: Remove Legacy Mode
- Delete `--no-tui` argument
- Delete the legacy consumer loop
- Delete `display.py` (legacy terminal facade)
- Delete `formatting_ansi.py` (ANSI rendering, only used by legacy mode)
- Remove legacy startup prints (TUI handles its own status display)
- Remove legacy state dict (TUI manages its own state)
- Clean up imports of deleted modules

### Sprint 2: Hot-Reload for TUI
- Expand `_check_reload()` to watch ALL non-proxy modules (formatting, analysis, colors, tui/*)
- Integrate reload detection into the TUI event loop
- After reload: re-render current view with new module code
- Ensure reload is safe (no stale references, no partial state)

## Verdict: CONTINUE

Clear approach. Two sequential sprints: remove dead code first, then add proper hot-reload.
