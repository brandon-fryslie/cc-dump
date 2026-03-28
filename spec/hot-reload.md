# Hot-Reload

> Status: draft
> Last verified against: not yet

## Overview

cc-dump is a development tool for observing Claude Code API traffic. Developers using it are simultaneously developing *it* -- tweaking formatting rules, adjusting color palettes, refining rendering logic, and adding new panel views. Without hot-reload, every change to these pure-logic modules would require restarting the proxy, reconnecting Claude Code, and losing the accumulated conversation history that makes the change visible. Hot-reload eliminates that cycle: save a file, see the result in under three seconds, with all conversation data intact.

From the user's perspective, hot-reload means: edit any formatting, rendering, or widget code, save the file, and the TUI updates in place. Conversation history, scroll position, panel state, and accumulated analytics all survive. The HTTP proxy never restarts. If you edit a file that *cannot* be hot-reloaded (the proxy itself, the app shell), the TUI warns you that a full restart is needed.

## What Triggers a Reload

The system uses OS-native file watching (via `watchfiles`) on the cc-dump package source directory. Any write to a `.py` file in the watched tree is detected.

**Reloadable file changes** are debounced: the system waits for a 2-second quiet period after the last change before executing the reload. This prevents partial reloads during multi-file saves or editor "save all" operations.

**Any single reloadable file change triggers a full reload of all reloadable modules.** There is no partial reload -- every reload reloads the entire reloadable set in dependency order. This is a deliberate simplicity choice: the reload is fast enough that eliminating partial-reload edge cases is worth the cost of reloading unchanged modules.

**Non-reloadable file changes** (stable boundary files) do not trigger a reload. Instead, the system immediately updates a staleness indicator in the TUI showing which stable files have changed since the app started, signaling that a full restart is needed to pick up those changes.

**If `watchfiles` is not installed**, hot-reload is silently disabled. The app logs an informational message and continues normally.

## What Survives a Reload

The following state is preserved across every hot-reload cycle:

- **Conversation data.** All conversation turns, including their formatted block structures and any active streaming state. This data lives in a `DomainStore` that is not part of the reload -- widgets re-bind to it after replacement.
- **Scroll position.** The vertical and horizontal scroll offset of each conversation view.
- **Follow mode state.** Whether the view is auto-scrolling to follow new content.
- **View overrides.** Per-block expansion overrides (user clicked to expand/collapse a specific block).
- **Panel state.** Which side panel is active, and any intra-panel state (e.g., which stats view is selected within the session panel).
- **Panel visibility.** Whether the logs panel and info panel are shown or hidden.
- **Reactive store state.** The `ViewStore` and `SettingsStore` (SnarfX reactive stores) survive via reconciliation -- the store instances persist, and their schemas and reactions are updated to match the reloaded module definitions.
- **Search query.** If search was active, the query text is preserved and search is re-executed with the new rendering code after widget replacement.
- **Search saved filters and scroll position.** The filter state and scroll position that were active before search began are captured and restored.

## What Resets on Reload

- **Search phase and highlights.** An active search is reset to inactive, then re-executed if a query was present. Match indices, highlight overlays, and debounce timers are discarded.
- **Rendered strips.** All pre-rendered Rich text strips are discarded and re-rendered from the surviving block data using the new rendering code. This is the point -- you changed the rendering, so you see the new rendering.
- **Widget instances.** Every swappable widget (conversation views, panels, logs, info panel, footer) is destroyed and recreated from the reloaded class definitions. State transfers via `get_state()` / `restore_state()`.
- **Log panel content.** The debug log panel's message buffer does not survive. It starts empty after each reload.
- **Ephemeral overlay panels.** Transient panels (keys panel, debug settings, settings, launch config) are removed before replacement. Their visibility keys in the store are preserved, so store reactions will re-create them after the pause ends.

## The Stable/Reloadable Boundary

Every module in cc-dump falls into exactly one of two categories. This classification is a contract: it determines import style, reload behavior, and what invariants the module must maintain.

### Reloadable Modules

Reloadable modules contain pure functions, class definitions, data constants, and rendering logic. They hold no long-lived state of their own. On reload, `importlib.reload()` replaces their module-level definitions with fresh versions.

The authoritative list is `_RELOAD_ORDER` in `hot_reload.py`. At time of writing, this includes approximately 40 modules spanning:

- **Core logic:** `filter_registry`, `palette`, `analysis`, `formatting_impl`, `formatting`, `coerce`, `segmentation`
- **TUI configuration:** `input_modes`, `action_config`, `category_config`, `panel_registry`
- **App stores:** `launch_config`, `error_models`, `settings_store`, `view_store`, `domain_store`
- **Rendering pipeline:** `search`, `search_controller`, `rendering_impl`, `rendering`, `dump_formatting`
- **Widget definitions:** `chip`, `store_widget`, `follow_mode`, `custom_footer`, `panel_renderers`, `stream_registry`, `event_handlers`, `error_indicator`, `info_panel`, `keys_panel`, `settings_panel`, `debug_settings_panel`, `launch_config_panel`, `settings_launch_controller`, `session_panel`, `widget_factory`, `dump_export`, `theme_controller`, `action_handlers`, `lifecycle_controller`
- **Pipeline:** `router`

Modules are reloaded in dependency order (leaves first, dependents after). If module A depends on module B, B is reloaded before A so that A's reload picks up B's new definitions.

**Contract for reloadable modules:** A reloadable module must not hold live references to app state, running threads, or system resources. It may define classes, functions, constants, and dispatch tables. If it needs runtime state, that state must live in a store or the app instance, not in module globals.

### Stable Boundary Modules

Stable boundary modules hold live state that cannot be safely replaced at runtime: running HTTP server threads, the Textual app instance, TLS certificate state, tmux pane references, and the reload system itself.

The authoritative list is `_EXCLUDED_FILES` and `_EXCLUDED_MODULES` in `hot_reload.py`. At time of writing:

| Module | Why it cannot reload |
|--------|---------------------|
| `pipeline/proxy.py` | Running HTTP server thread |
| `pipeline/forward_proxy_tls.py` | Holds live TLS/crypto state |
| `pipeline/response_assembler.py` | Imported by proxy.py, part of stable pipeline |
| `pipeline/event_types.py` | Stable type definitions shared across boundaries |
| `app/tmux_controller.py` | Holds live tmux pane references |
| `io/stderr_tee.py` | Holds live `sys.stderr` reference |
| `cli.py` | Entry point, already executed |
| `hot_reload.py` | The reloader itself |
| `tui/app.py` | The live Textual App instance |
| `tui/hot_reload_controller.py` | Mutates app widget tree during reload |

**Contract for stable modules:** A stable module that calls into reloadable code must use module-level imports (`import cc_dump.module`), never direct imports (`from cc_dump.module import func`). Direct imports bind to the function object at import time; after reload, the binding is stale and points to the old code. Module-level imports go through the module object, which `importlib.reload()` updates in place.

After each reload, the system performs a single alias-refresh pass across all loaded `cc_dump.*` modules. This catches cases where a reloadable module used `from` imports of another reloadable module -- the old function/class references are replaced with their post-reload equivalents by matching on object identity. This is a safety net; the primary defense is the import convention.

### Staleness Detection for Stable Modules

When a stable boundary file is edited, the system cannot reload it, but it can tell the developer. At startup, content hashes (SHA-256) are recorded for all files on a staleness watchlist. This watchlist includes essentially all excluded files and modules minus boilerplate -- it is not a small curated subset but rather a comprehensive list of stable boundary files that could diverge from the running code. On every file change event (no debounce -- immediate), current hashes are compared against the startup hashes. Any divergence is reported to the `ViewStore` as a list of stale file names, which surfaces in the TUI's error indicator.

This gives the developer clear feedback: "You edited `proxy.py` -- restart to pick up that change."

## The Widget Hot-Swap Protocol

All widgets that participate in hot-reload must implement two methods:

- **`get_state() -> dict`**: Extract the widget's preservable state as a plain dictionary. Called on the old widget instance before it is removed from the DOM.
- **`restore_state(state: dict) -> None`**: Apply state from a previous instance. Called on the new widget instance after creation but before mounting. Must handle missing keys gracefully with defaults.

The swap sequence for each widget is:

1. `get_state()` on old instance (captures state)
2. Factory function creates new instance from reloaded class
3. Protocol validation confirms new instance has required methods
4. `restore_state(state)` on new instance (transfers state)
5. Old instance is removed from DOM
6. New instance is mounted in the same position with the same CSS ID

The system uses a create-before-remove pattern: all new widgets are fully created and state-restored before any old widgets are touched. If creation fails, old widgets remain in the DOM and the app continues working.

During the swap, all SnarfX reactions are paused to prevent reactions from querying widgets during the gap between removal and mounting.

## Reload Sequence (End-to-End)

When a developer saves a reloadable file, the following happens:

1. **File change detected** by `watchfiles` async iterator
2. **Event emitted** to an `EventStream`
3. **Two parallel paths diverge:**
   - Path A (immediate): staleness state updated for all watched files
   - Path B (debounced): if the changed file is reloadable, a 2-second debounce timer starts
4. **Debounce fires** after 2 seconds of quiet
5. **Reload scheduled asynchronously** via `call_later` on the Textual event loop
6. **All reloadable modules reloaded** via `importlib.reload()` in dependency order
7. **Alias refresh pass** updates stale `from` import bindings across all `cc_dump.*` modules
8. **Search state reset** (debounce timer stopped, phase set to INACTIVE)
9. **Theme rebuilt** from reloaded palette/rendering modules
10. **Reactive stores reconciled** (schema + reactions updated to match reloaded definitions)
11. **All widgets replaced** via the hot-swap protocol (capture state, create new, restore state, remove old, mount new)
12. **Conversations re-rendered** with new rendering code against surviving block data
13. **Search re-executed** if a query was active before reload
14. **Notification shown** ("N modules updated")

If any step fails, the error is logged and surfaced as a notification. The system continues with partial results rather than aborting entirely -- a syntax error in one module does not prevent other modules from reloading.

## Edge Cases

- **Rapid successive saves:** The 2-second debounce collapses them into a single reload.
- **Syntax error in a reloadable module:** That module's reload fails with a logged exception. Other modules continue reloading. The app continues with the last good version of the failed module. Saving a fix triggers another reload cycle.
- **New module added but not in `_RELOAD_ORDER`:** Changes to the file are detected by the watcher but `is_reloadable()` returns `False` for such files, so the debounce filter does not fire and no reload is triggered. The file is effectively ignored by the hot-reload system.
- **Module removed from disk:** `importlib.reload()` will fail for that module. The error is caught and logged; other modules continue.
- **Widget protocol violation:** If a new widget instance does not implement `get_state`/`restore_state`, a `TypeError` is raised during the mount phase. The error is caught and reported via notification. [UNVERIFIED: whether old widgets remain mounted in this case or are already removed.]
