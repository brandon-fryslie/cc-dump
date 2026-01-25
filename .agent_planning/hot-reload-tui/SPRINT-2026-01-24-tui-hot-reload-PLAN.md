# Sprint: tui-hot-reload - Hot-Reload All Non-Proxy Modules in TUI
Generated: 2026-01-24
Confidence: HIGH: 2, MEDIUM: 2, LOW: 0
Status: PARTIALLY READY

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

**Acceptance Criteria:**
- [ ] Watches all `.py` files in `src/cc_dump/` and `src/cc_dump/tui/` except `proxy.py`
- [ ] Polls on a 1-second interval (or on each event, whichever is more responsive)
- [ ] Detects modification time changes
- [ ] Reports which files changed (for debug logging)

**Technical Notes:**
- Reuse the mtime-polling approach (simple, no external deps)
- Watch list: `colors.py`, `formatting.py`, `analysis.py`, `schema.py`, `store.py`, `router.py`, `tui/app.py`, `tui/widgets.py`, `tui/rendering.py`
- `cli.py` itself doesn't need watching (it's the entry point / orchestrator)
- `proxy.py` explicitly excluded (stable boundary)

### P1: Implement ordered module reload
**Confidence: HIGH**

**Acceptance Criteria:**
- [ ] Modules reloaded in dependency order (leaves first, dependents after)
- [ ] Reload order: `colors` → `analysis` → `formatting` → `tui.rendering` → `tui.widgets` → `tui.app`
- [ ] `store.py`, `schema.py`, `router.py` also reloaded if changed (they have no downstream dependents in the display path)
- [ ] Reload is all-or-nothing for the display path (if any display module changed, reload all display modules)
- [ ] Errors during reload are caught and logged, never crash the app

**Technical Notes:**
- Dependency order for display path: `colors` → `analysis` → `formatting` → `tui.rendering` → `tui.widgets` → `tui.app`
- `store.py` and `router.py` are independent — reload only if they themselves changed
- After reload, TUI app's imports will point to old module objects unless re-fetched. The `_handle_event` method uses `format_request` and `format_response_event` which are imported at module level in `tui/app.py`. After `importlib.reload(cc_dump.tui.app)`, these bindings update.

### P2: Integrate reload into TUI event loop
**Confidence: MEDIUM**

**Acceptance Criteria:**
- [ ] Reload check happens in the drain worker thread (before posting event to main thread)
- [ ] After reload detection, the app re-renders the conversation view with new code
- [ ] No race conditions between reload and event handling
- [ ] Visual indicator when reload occurs (e.g., flash footer or log message)

#### Unknowns to Resolve
- How does Textual handle `importlib.reload()` of the running App subclass? The app instance stays alive but its class definition changes. Methods already bound to the instance won't change. The safer approach may be to only reload the modules the app *uses* (formatting, rendering, widgets) but NOT `tui/app.py` itself.
- If we reload `tui/widgets.py`, do existing widget instances pick up new methods? Likely not — we'd need to re-create widgets or only reload the rendering/formatting logic.

#### Exit Criteria
- Prototype confirms: reloading `formatting.py` + `tui/rendering.py` causes next event to render with new code
- Determine if widget reload requires widget recreation or just re-render

### P3: Ensure no stale references after reload
**Confidence: MEDIUM**

**Acceptance Criteria:**
- [ ] After reload, `format_request()` and `format_response_event()` use new code
- [ ] After reload, `render_block()` and `render_blocks()` use new code
- [ ] No cached function references in closures or instance attributes that bypass reload
- [ ] Widget `rerender()` uses freshly-imported rendering functions

#### Unknowns to Resolve
- The TUI app imports `format_request`, `format_response_event` at the top of `tui/app.py`. After `importlib.reload(cc_dump.formatting)`, these names in `tui/app.py`'s namespace still point to the OLD functions. Options:
  1. Always access via `cc_dump.formatting.format_request(...)` (module-level access, auto-updates after reload)
  2. Reload `tui/app.py` too (but instance methods won't update)
  3. Use a thin indirection layer

#### Exit Criteria
- Chosen approach confirmed working: editing `formatting.py` mid-session causes next request to use new formatting code

## Dependencies
- Sprint 1 (remove-legacy-mode) must complete first — removes conflicting hot-reload code

## Risks
- **Widget instance methods**: Reloading `tui/widgets.py` won't update methods on existing widget instances. Mitigation: only reload data-path modules (formatting, rendering, analysis) and re-render existing widgets.
- **Textual internals**: Textual may cache widget references or class metadata. Mitigation: don't reload `tui/app.py` or `tui/widgets.py` — only reload the pure-function modules they call.
- **Thread safety**: Reload happens in worker thread, rendering in main thread. Mitigation: use `call_from_thread` to perform reload + re-render atomically on main thread.
