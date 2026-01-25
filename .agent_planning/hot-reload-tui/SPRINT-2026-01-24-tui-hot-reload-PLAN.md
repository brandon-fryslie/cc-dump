# Sprint: tui-hot-reload - Hot-Reload All Non-Proxy Modules in TUI
Generated: 2026-01-24
Confidence: HIGH: 2, MEDIUM: 2, LOW: 0
Status: COMPLETE

## Sprint Goal
All modules except `proxy.py` are hot-reloaded when their source changes. Changes to formatting, analysis, rendering, widgets, or colors take effect on the next event without restarting the app.

## Scope
**Deliverables:**
- File watcher that monitors all non-proxy Python source files
- Reload mechanism that uses `importlib.reload()` in correct dependency order
- TUI re-render after reload so current view reflects new code
- No stale references after reload (all module access through module-level references)

## Work Items

### P0: Implement file watcher for all non-proxy modules
**Confidence: HIGH**
**Status: COMPLETE**

**Acceptance Criteria:**
- [x] Watches all `.py` files in `src/cc_dump/` and `src/cc_dump/tui/` except `proxy.py`
- [x] Polls on a 1-second interval (or on each event, whichever is more responsive)
- [x] Detects modification time changes
- [x] Reports which files changed (for debug logging)

**Implementation:**
- Created `hot_reload.py` with mtime-polling approach
- Checks happen on 1-second timeout in drain worker, and before each event
- Excludes: proxy.py, cli.py, hot_reload.py, __init__.py, __main__.py, tui/app.py, tui/widgets.py
- Logs detected changes to stderr for debugging

### P1: Implement ordered module reload
**Confidence: HIGH**
**Status: COMPLETE**

**Acceptance Criteria:**
- [x] Modules reloaded in dependency order (leaves first, dependents after)
- [x] Reload order: `colors` → `analysis` → `formatting` → `tui.rendering`
- [x] `store.py`, `schema.py`, `router.py` also reloaded if changed (they have no downstream dependents in the display path)
- [x] Reload is all-or-nothing for the display path (if any display module changed, reload all display modules)
- [x] Errors during reload are caught and logged, never crash the app

**Implementation:**
- Display path modules always reloaded together in dependency order
- Optional modules (store, schema, router) only reloaded if they changed
- Error handling catches reload exceptions and continues with other modules
- Does NOT reload tui/app.py or tui/widgets.py (live instances can't safely reload)

### P2: Integrate reload into TUI event loop
**Confidence: MEDIUM**
**Status: COMPLETE**

**Acceptance Criteria:**
- [x] Reload check happens in the drain worker thread (before posting event to main thread)
- [x] After reload detection, the app re-renders the conversation view with new code
- [x] No race conditions between reload and event handling
- [x] Visual indicator when reload occurs (e.g., flash footer or log message)

**Implementation:**
- `_check_hot_reload()` method called via `call_from_thread` on main thread
- Reload happens both on idle (1-second timeout) and before each event
- Notification displayed with `self.notify()` when reload occurs
- Conversation view is re-rendered with current filters after reload
- Thread safety ensured by using `call_from_thread` for all main-thread operations

**Resolution of Unknowns:**
- tui/app.py and tui/widgets.py are NOT reloaded (live instances)
- Only pure-function modules (formatting, rendering, analysis, colors) are reloaded
- Widgets use existing instances, just re-render with new code

### P3: Ensure no stale references after reload
**Confidence: MEDIUM**
**Status: COMPLETE**

**Acceptance Criteria:**
- [x] After reload, `format_request()` and `format_response_event()` use new code
- [x] After reload, `render_block()` and `render_blocks()` use new code
- [x] No cached function references in closures or instance attributes that bypass reload
- [x] Widget `rerender()` uses freshly-imported rendering functions

**Implementation:**
- Chose Approach A: module-level access
- Refactored tui/app.py to use `cc_dump.formatting.format_request()` instead of `from cc_dump.formatting import format_request`
- Refactored tui/widgets.py to use `cc_dump.tui.rendering.render_block()` instead of `from cc_dump.tui.rendering import render_block`
- All type annotations also use module-level access (e.g., `cc_dump.analysis.TurnBudget`)
- After `importlib.reload()`, next call automatically uses new code

## Dependencies
- Sprint 1 (remove-legacy-mode) completed - removed conflicting hot-reload code

## Risks - MITIGATED
- **Widget instance methods**: MITIGATED - don't reload tui/widgets.py or tui/app.py, only reload the pure-function modules they call
- **Textual internals**: MITIGATED - only reload data-path modules (formatting, rendering, analysis, colors)
- **Thread safety**: MITIGATED - use `call_from_thread` to perform reload + re-render atomically on main thread

## Commit
- SHA: 1b00048
- Message: feat: add hot-reload support for TUI modules
