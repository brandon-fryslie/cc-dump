# Hot-Reload Architecture Evaluation

## Executive Summary

The hot-reload system is **well-architected for its core purpose** — reloading rendering and formatting code during development without losing conversation state. The dependency-ordered `importlib.reload()` approach is the right choice for Python, and the widget swap protocol is solid. However, it has **known blind spots**, **silent state losses**, and **untapped potential** for unifying with session persistence.

---

## 1. What Works Well

### Dependency-ordered full reload
Every file change triggers a reload of ALL 14 reloadable modules in topological order. This eliminates partial-reload bugs entirely. The cost (~50ms for 14 `importlib.reload()` calls) is negligible compared to the widget rebuild.

### Blocks as pure data
The `FormattedBlock` hierarchy is the linchpin. Blocks are plain dataclasses with no method references to reloaded functions. Category resolution, rendering, and visibility all happen via fresh function lookups at render time. This means blocks survive reloads perfectly.

### Create-before-remove widget swap (`hot_reload_controller.py:110-196`)
New widgets are fully constructed and state-restored before old widgets are removed. If creation fails, old widgets stay in the DOM. This is crash-safe.

### Import discipline
Stable boundary modules use `import cc_dump.module` (module-level references), reloadable modules use `from cc_dump.module import X` (re-executed on reload). The `TestImportValidation` test enforces this at CI time.

### Type-name dispatch instead of `isinstance`
Renderers are keyed by `type(block).__name__` strings, not class identity. This means `isinstance(old_block, NewClass)` failures are avoided entirely.

### Fault-tolerant reload
Each module reload is individually try-caught. A syntax error in `palette.py` doesn't prevent `widget_factory.py` from reloading.

---

## 2. What's Bad / Poor Cost-Benefit

### `widgets.py` is a stale-reference trap
`widgets.py` uses `from cc_dump.tui.widget_factory import ConversationView, ...` — a non-reloadable module holding `from` imports to a reloadable module. After reload, `widgets.py.ConversationView` is the OLD class. Nothing currently breaks because all runtime widget access goes through CSS ID queries (`app._get_conv()` → `query_one("#conv")`), but:
- Any future code that does `isinstance(widget, ConversationView)` via the widgets.py import will fail
- The module's stated purpose ("re-exports for backwards compatibility") is misleading — it's a trap for future developers

### Scroll position is silently lost on reload
`ConversationView.get_state()` captures `all_blocks`, `follow_mode`, `streaming_states` — but NOT scroll offset or scroll anchor. If the user is scrolled to the middle of a conversation and a reload fires, they jump to the bottom (follow mode is preserved, but if follow mode was off, position is lost). This is the single most user-visible reload artifact.

### Search is killed, not preserved
Active search is unconditionally cancelled on reload (`hot_reload_controller.py:65-71`). The comment says "state references may be stale" — but the search state is just a query string and match indices. These could be preserved cheaply.

### No visibility filter preservation across reload
The `_is_visible`, `_is_full`, `_is_expanded` reactive dicts live on the app instance (which isn't reloaded), so they DO survive. But per-block expansion overrides (`block.expanded`) survive only because blocks themselves survive as data. If a user has expanded 15 individual blocks and then a reload fires — they're fine. This actually works, it's just not tested.

### Code duplication in file scanning
`_scan_mtimes()`, `has_changes()`, and `_get_changed_files()` contain nearly identical dir-scanning loops (3x the same os.listdir + exclusion logic). Any change to exclusion rules must be replicated in all three.

---

## 3. What Will Break It

### Adding a new reloadable module and forgetting `_RELOAD_ORDER`
If someone creates `src/cc_dump/tui/foo.py`, it will be WATCHED (mtime changes detected) but NOT RELOADED (not in `_RELOAD_ORDER`). The file change triggers a reload of all OTHER modules, but `foo.py` keeps its original code. `TestHotReloadModuleStructure` partially catches this — it validates all `.py` files in watch dirs are either in `_RELOAD_ORDER` or explicitly excluded. But a developer must know to add to one of these lists.

### `from` imports in stable boundary modules
If someone adds `from cc_dump.formatting import SomeNewType` in `app.py` or `action_handlers.py`, that reference is forever stale after reload. The `TestImportValidation` test catches this for known stable modules, but it only checks modules listed in the test — a new stable module could slip through.

### Module-level side effects in reloadable modules
If a reloadable module appends to a global list at import time (`MY_LIST.append(handler)`), reload would double-append. Currently none do this, but it's an easy mistake.

### Circular imports between reloadable modules
The reload order is linear. If module A and B develop a circular dependency, `importlib.reload(A)` might fail because B's new version isn't loaded yet. Currently the dependency graph is acyclic.

### `segmentation.py` is in `_RELOAD_ORDER` but consumed via lazy `from` imports
`rendering.py` imports segmentation at call time (`from cc_dump.segmentation import segment` inside function bodies). This works because segmentation IS reloaded before rendering. But the cached `block._segment_result` is stale — it was computed by the OLD segmentation code. The cache is only invalidated when the block is re-rendered, which happens on the same reload cycle, so it's fine in practice. But if segmentation were moved out of `_RELOAD_ORDER`, cached results would persist incorrectly.

---

## 4. Where It's Already Broken

### Scroll position loss (confirmed)
`get_state()` at `widget_factory.py:1070-1094` does NOT include `_scroll_anchor` or `scroll_offset`. After reload, if follow_mode is False, the user's scroll position is lost.

### `widgets.py` class identity divergence (latent)
After reload, `cc_dump.tui.widgets.ConversationView` (old class) != `cc_dump.tui.widget_factory.ConversationView` (new class). Not currently triggered by any code path, but a latent bug.

### File watching misses new files
`_scan_mtimes()` is called once at `init()`. New `.py` files created after startup are watched (they appear in `os.listdir()` during `_get_changed_files()`), BUT their initial mtime is never seeded. The first time they're seen, `path in _mtimes` is False, so they're skipped (`_mtimes[path] = mtime` is set but no change is reported). They'll be detected on the SECOND modification. This means creating a new file doesn't trigger a reload — only editing it twice does.

---

## 5. How to Make It More Reliable

### A. Preserve scroll position across reload
Add `_scroll_anchor` (or `scroll_offset.y`) to `get_state()` / `restore_state()`. After rebuild, resolve the anchor to restore scroll position.

### B. Unify the 3 file-scanning loops
Extract a single `_iter_watched_files() -> Iterator[tuple[str, str]]` that yields `(abs_path, rel_path)` after applying exclusion filters. Use it in `_scan_mtimes()`, `has_changes()`, and `_get_changed_files()`.

### C. Detect new files on first sight
In `_get_changed_files()`, treat `path not in _mtimes` as a change (new file = changed file). This makes creating a new module trigger an immediate reload.

### D. Delete `widgets.py` or make it a true facade
Either delete it entirely (update all imports to use `widget_factory` directly) or make it reload-aware by having it re-import on access. The current "re-export" pattern is a foot-gun.

### E. Preserve search state across reload
Instead of cancelling search, save the query string and current match index in the state dict. After reload, re-execute the search with the same query.

---

## 6. How to Get More Value: Unified Session Persistence

### The Core Insight

Hot-reload's `get_state()`/`restore_state()` protocol already defines the serialization boundary for every widget. The same protocol could serve three use cases:

| Use Case | When | Current Status |
|----------|------|----------------|
| Hot-reload | File change during dev | Working |
| App exit/restart | Quit and relaunch | NOT implemented (state lost) |
| Session resume | Reconnect to recording | NOT implemented |

### What would unified persistence look like?

**Step 1: Make `get_state()` return JSON-serializable data.**
Currently, `get_state()` returns dicts containing `FormattedBlock` objects (dataclass instances). These can't be JSON-serialized directly. Two approaches:
- (a) Add `to_dict()` / `from_dict()` to FormattedBlock hierarchy
- (b) Use `pickle` for disk persistence (fast but fragile across code changes)
- (c) Don't persist blocks at all — re-derive them from HAR on restart

Option (c) is the most architecturally sound: HAR files are already the source of truth. On restart, replay the HAR into the formatting pipeline to reconstruct blocks, then restore the lightweight UI state (scroll position, visibility filters, follow mode) from a small JSON sidecar.

**Step 2: Save UI state on exit.**
On `on_unmount()`, write a `~/.config/cc-dump/session-state.json`:
```json
{
  "har_path": "/path/to/recording.har",
  "scroll_position": 4523,
  "follow_mode": false,
  "visibility": {"headers": [false, false, false], "user": [true, true, false], ...},
  "search_query": "error",
  "panel_visibility": {"economics": true, "timeline": false, "logs": false}
}
```

**Step 3: Restore on startup.**
If `--replay latest` (or a new `--resume` flag) is used and a session-state file exists for that HAR, replay the HAR (already works) and then apply the UI state from the sidecar.

**Step 4: Hot-reload uses the same state shape.**
`get_state()` already returns this shape (minus the HAR path). The only difference is that hot-reload preserves blocks in memory (no serialization needed), while disk persistence re-derives blocks from HAR. The UI state (scroll, filters, panels) is identical.

### How much can hot-reload actually reload?

**What it CAN reload:** Any module that produces output from data — formatting, rendering, colors, analysis, panel renderers, search, footer. This covers ~80% of the codebase by line count.

**What it CANNOT reload:**
- `app.py` — the Textual App instance owns the event loop; replacing it means restarting the TUI
- `proxy.py` — the HTTP server thread; reloading would drop active connections
- `cli.py` — already executed, just the entry point
- Controller modules (`action_handlers`, `search_controller`, etc.) — these hold references to `app` and its widgets; reloading them would create stale closures
- `event_types.py` — type definitions used across boundaries; reloading would break isinstance checks

**What about child module changes?** If `formatting.py` imports from `analysis.py`, and `analysis.py` changes:
- Both are in `_RELOAD_ORDER`, analysis before formatting
- `analysis.py` is reloaded first (fresh module object)
- `formatting.py` is reloaded second, its `from cc_dump.analysis import ...` re-executes, getting fresh references
- Result: **transitive changes work correctly** within the reloadable set

**What about changes to stable modules?** If someone edits `event_types.py`:
- It's in `_EXCLUDED_FILES`, so the change is NOT detected
- No reload happens
- If the edit adds a new field to an event type, no code picks it up until restart
- This is correct behavior — stable modules need a restart

### How do we detect state loss?

Currently: we don't. State loss (scroll position, search) happens silently. Options:
1. **Checksum state before/after reload** — hash the state dict before reload and after restore; if they differ, log what was lost
2. **Structured state contract** — define a `StateFields` enum that each widget declares; the reload controller verifies all declared fields survive the roundtrip
3. **Test coverage** — the simplest approach: write a test that populates state, round-trips through get_state/restore_state, and asserts equality

### Should we save session state to disk?

**Yes, but minimally.** The HAR file is already the source of truth for content. We only need to persist:
- Visibility filter state (already in `settings.json` via Ctrl+F1-F8, could auto-save the "current" state)
- Scroll position (just an integer)
- Follow mode (boolean)
- Panel visibility (5 booleans)
- Active search query (string, optional)

This is ~200 bytes of JSON. The existing `settings.py` with its atomic-write mechanism is perfect for this.

---

## 7. Recommended Next Steps (Priority Order)

1. **Fix scroll position preservation** — Add to get_state/restore_state. Immediate UX improvement. ~30 min.
2. **Unify file-scanning loops** — Extract `_iter_watched_files()`. Reduces maintenance burden. ~15 min.
3. **Auto-save current visibility state on exit** — Write to `settings.json` under a `"current"` key. Restore on startup. ~1 hr.
4. **Detect new files on first sight** — Treat `path not in _mtimes` as change. ~5 min.
5. **Address `widgets.py` stale references** — Either delete or document the trap. ~15 min.
6. **State roundtrip tests** — Test that scroll position, block expansion, and panel visibility survive get_state/restore_state. ~30 min.
7. **Session resume from HAR + sidecar** — The big feature. Replay HAR + apply UI state. ~half day.
