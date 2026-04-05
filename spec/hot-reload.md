# Hot-Reload

## Overview

cc-dump is a development tool for observing Claude Code API traffic. Developers using it are simultaneously developing *it* -- tweaking formatting rules, adjusting color palettes, refining rendering logic, and adding new panel views. Without hot-reload, every change to these pure-logic modules would require restarting the proxy, reconnecting Claude Code, and losing the accumulated conversation history that makes the change visible. Hot-reload eliminates that cycle: save a file, see the result in under three seconds, with all conversation data intact.

From the user's perspective, hot-reload means: edit any formatting, rendering, or widget code, save the file, and the TUI updates in place. Conversation history, scroll position, panel state, and accumulated analytics all survive. The HTTP proxy never restarts. If you edit a file that *cannot* be hot-reloaded (the proxy itself, the app shell), the TUI warns you that a full restart is needed.

## What Triggers a Reload

The system uses OS-native file watching (via `watchfiles`) on the cc-dump package source directory. `hot_reload.init()` is called with the package root (e.g., `/path/to/src/cc_dump`) and registers both the root and the `tui/` subdirectory as watch paths. It also seeds the staleness hash cache and builds the reloadable path set from `_RELOAD_ORDER`. Any write to a `.py` file in the watched tree is detected.

**Reloadable file changes** are debounced: the system waits for a 2-second quiet period after the last change before executing the reload. This prevents partial reloads during multi-file saves or editor "save all" operations. The debounce constant is `_DEBOUNCE_S = 2.0` in `hot_reload_controller.py`.

**Any single reloadable file change triggers a full reload of all reloadable modules.** There is no partial reload -- every reload reloads the entire reloadable set in dependency order. This is a deliberate simplicity choice: the reload is fast enough that eliminating partial-reload edge cases is worth the cost of reloading unchanged modules.

The filter that distinguishes reloadable from non-reloadable changes runs *before* the debounce. `_has_reloadable_changes()` checks each changed path against the reloadable path set (derived at `init()` time from `_RELOAD_ORDER` by stripping the `cc_dump.` prefix, converting dots to slashes, and appending `.py`). If none of the changed files are reloadable, the debounce never fires and no reload occurs -- only the staleness subscriber runs.

**Non-reloadable file changes** (stable boundary files) do not trigger a reload. Instead, the system immediately updates a staleness indicator in the TUI showing which stable files have changed since the app started, signaling that a full restart is needed to pick up those changes.

**If `watchfiles` is not installed**, hot-reload is silently disabled. The app logs an informational message and continues normally.

**Watcher lifecycle:** `start_file_watcher()` disposes any existing watcher stream before creating a new one (via `stop_file_watcher()`). The watcher runs as an async `for` loop over `watchfiles.awatch()`, emitting each changeset to an `EventStream`. The stream is stored in the module global `_watcher_stream` and disposed on shutdown.

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

The authoritative list is `_RELOAD_ORDER` in `hot_reload.py`. At time of writing, this includes 42 modules spanning:

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
| `__init__.py` | Module init |
| `__main__.py` | Entry point |
| `hot_reload.py` | The reloader itself |
| `tui/app.py` | The live Textual App instance |
| `tui/hot_reload_controller.py` | Mutates app widget tree during reload |

**Contract for stable modules:** A stable module that calls into reloadable code must use module-level imports (`import cc_dump.module`), never direct imports (`from cc_dump.module import func`). Direct imports bind to the function object at import time; after reload, the binding is stale and points to the old code. Module-level imports go through the module object, which `importlib.reload()` updates in place.

After each reload, the system performs a single alias-refresh pass across all loaded `cc_dump.*` modules. This catches cases where a reloadable module used `from` imports of another reloadable module -- the old function/class references are replaced with their post-reload equivalents by matching on object identity. This is a safety net; the primary defense is the import convention.

The alias refresh algorithm works in three phases:

1. **Snapshot** (`_snapshot_reloaded_exports`): Before any module is reloaded, capture a `{module_name: {export_name: old_object}}` mapping for every module in `_RELOAD_ORDER`. Only alias-refreshable exports are captured (see filtering rules below).
2. **Build replacement map** (`_build_alias_replacements`): After all modules are reloaded, compare pre-reload objects to post-reload objects. For each export where `new_value is not old_value`, record `{id(old_value): new_value}` in a replacement dict keyed by Python object identity.
3. **Apply** (`_apply_alias_replacements`): Walk every `cc_dump.*` module dict in `sys.modules`. For each binding whose `id()` appears in the replacement map, rebind it to the new object. This updates stale `from` import aliases in a single pass regardless of which module holds the alias.

The alias refresh is selective: only exports whose `__module__` attribute (or whose `type(value).__module__` attribute) matches their source module are tracked. This restriction prevents accidental rebinding caused by shared identities. Primitives (`str`, `bytes`, `int`, `float`, `complex`, `bool`, `tuple`, `frozenset`, `list`, `dict`, `set`, and `None`) are unconditionally excluded from alias refresh because Python interns and caches these values, which would cause false identity matches across unrelated modules.

### Staleness Detection for Stable Modules

When a stable boundary file is edited, the system cannot reload it, but it can tell the developer. At startup, content hashes (SHA-256) are recorded for all files on a staleness watchlist (`_STALENESS_WATCHLIST`). This watchlist is the union of `_EXCLUDED_FILES` and `_EXCLUDED_MODULES` minus boilerplate (`__init__.py`, `__main__.py`) and `hot_reload.py` itself (editing the reloader while running is nonsensical -- no TUI indicator is shown). The watchlist entries use relative paths:

- From `_EXCLUDED_FILES`: `pipeline/proxy.py`, `pipeline/forward_proxy_tls.py`, `cli.py`, `pipeline/event_types.py`, `pipeline/response_assembler.py`, `app/tmux_controller.py`, `io/stderr_tee.py`
- From `_EXCLUDED_MODULES`: `tui/app.py`, `tui/hot_reload_controller.py`

On every file change event (no debounce -- immediate, via a second subscriber on the same `EventStream`), current hashes are compared against the startup hashes. Any divergence is reported to the `ViewStore` as a list of stale relative paths (e.g., `pipeline/proxy.py`), which surfaces in the TUI's error indicator.

`_iter_excluded_files` matches entries in `_STALENESS_WATCHLIST` by both filename (`path.name`) and relative path (`rel_str`). So an entry like `"cli.py"` matches any file named `cli.py` in the watched tree, while `"pipeline/proxy.py"` only matches the specific path. Membership in the staleness set is determined solely by `_STALENESS_WATCHLIST` -- the `_EXCLUDED_FILES` and `_EXCLUDED_MODULES` sets are not consulted at staleness-check time.

This gives the developer clear feedback: "You edited `proxy.py` -- restart to pick up that change."

## The Widget Hot-Swap Protocol

All widgets that participate in hot-reload must implement two methods:

- **`get_state() -> dict`**: Extract the widget's preservable state as a plain dictionary. Called on the old widget instance before it is removed from the DOM.
- **`restore_state(state: dict) -> None`**: Apply state from a previous instance. Called on the new widget instance after creation but before mounting. Must handle missing keys gracefully with defaults.

Protocol compliance is validated at runtime by `validate_widget_protocol()` in `protocols.py`. This function first checks the `HotSwappableWidget` runtime-checkable `Protocol` via `isinstance()`. If that fails, it falls back to manual inspection: verifying that `get_state` and `restore_state` exist as callable attributes. If validation fails, a `TypeError` is raised with a message identifying the failing widget and the specific violation (missing method or non-callable attribute).

The swap sequence for each widget is:

1. `get_state()` on old instance (captures state)
2. Factory function creates new instance from reloaded class
3. `validate_widget_protocol()` confirms new instance has required methods
4. `restore_state(state)` on new instance (transfers state)
5. Old instance is removed from DOM
6. New instance is mounted in the same position with the same CSS ID

The system uses a create-before-remove pattern: all new widgets are fully created and state-restored before any old widgets are touched. If creation or validation fails, the `TypeError` propagates and the entire replacement is aborted, leaving old widgets in the DOM.

The widget categories replaced are:

- **Conversation views.** One per session, looked up via `app._session_conv_ids`. Each swap captures the session key, CSS ID, widget state, parent container, and per-session `DomainStore` reference (from `app._session_domain_stores`). New instances are created via `widget_factory.create_conversation_view()`.
- **Cycling panels.** Created from `PANEL_REGISTRY` specs via `_resolve_factory()`. Panel CSS IDs and the `app._panel_ids` map are rebuilt from the registry on each reload.
- **Logs panel.** Created via `widget_factory.create_logs_panel()`.
- **Info panel.** Created via `info_panel.create_info_panel()`.
- **Footer.** Created as a new `StatusFooter()` instance (no state transfer -- the footer is stateless).

During the swap, all SnarfX reactions are paused via `stx.pause(app)` to prevent reactions from querying widgets during the gap between removal and mounting.

**Mount ordering:** After old widgets are removed, new widgets are mounted in a deterministic order relative to the `Header` widget: panels (in registry order) → conversation views (each mounted into its original parent container) → logs panel → info panel → footer. Identity assignment (CSS IDs and display visibility) happens before mounting via `_assign_replacement_identity()`.

## Reload Sequence (End-to-End)

When a developer saves a reloadable file, the following happens:

1. **File change detected** by `watchfiles` async iterator in `start_file_watcher()`
2. **Event emitted** to an `EventStream`
3. **Two parallel subscriber paths diverge:**
   - Path A (immediate): staleness state updated for all watched files via `_update_staleness()`
   - Path B (debounced): if the changed file passes `_has_reloadable_changes()`, a 2-second debounce timer starts
4. **Debounce fires** after 2 seconds of quiet
5. **Reload scheduled** via `app.call_later(_do_hot_reload, app)` on the Textual event loop
6. **All reloadable modules reloaded** via `importlib.reload()` in dependency order (`check_and_get_reloaded()`)
7. **Alias refresh pass** updates stale `from` import bindings across all `cc_dump.*` modules
8. **Search state reset** (debounce timer stopped, fresh `SearchState` created with default INACTIVE phase, search bar hidden)
9. **Theme rebuilt** from reloaded palette/rendering modules (`set_theme()` + `apply_markdown_theme()`)
10. **Reactive stores reconciled** (settings store and view store schemas + reactions updated to match reloaded definitions via `store.reconcile()`)
11. **All widgets replaced** via the hot-swap protocol: capture state → create new → validate protocol → restore state → remove ephemeral overlays → remove old → mount new
12. **Conversations re-rendered** with new rendering code against surviving block data (`conv.rerender(filters)`)
13. **Domain store re-bound** (`app._domain_store` set to active session store)
14. **Notification shown** ("[hot-reload] N modules updated")
15. **Search re-executed** if a query was active before reload

If any step fails, the error is logged and surfaced as a notification. The system continues with partial results rather than aborting entirely -- a syntax error in one module does not prevent other modules from reloading.

## Edge Cases

- **Rapid successive saves:** The 2-second debounce collapses them into a single reload.
- **Syntax error in a reloadable module:** That module's reload fails with a logged exception. Other modules continue reloading. The app continues with the last good version of the failed module. Saving a fix triggers another reload cycle.
- **New module added but not in `_RELOAD_ORDER`:** Changes to the file are detected by the watcher but `is_reloadable()` returns `False` (it checks against the set of relative paths derived from `_RELOAD_ORDER`), so the debounce filter does not fire and no reload is triggered. The file is effectively ignored by the hot-reload system.
- **Module not yet imported:** `check_and_get_reloaded()` only reloads modules already present in `sys.modules`. If a module is listed in `_RELOAD_ORDER` but was never imported (e.g., a lazily-loaded module), it is silently skipped.
- **Module removed from disk:** `importlib.reload()` will fail for that module. The error is caught and logged; other modules continue.
- **Widget protocol violation:** If a new widget instance does not implement `get_state`/`restore_state`, `validate_widget_protocol()` raises `TypeError`. This propagates through `_validate_and_restore_widget_state()` and aborts the replacement via the exception handler in `_do_hot_reload()`. Old widgets remain in the DOM and the app continues working because the exception is caught at the top level and surfaced as a notification.
- **Ephemeral panel removal after reload:** Ephemeral panels (KeysPanel, DebugSettingsPanel, SettingsPanel, LaunchConfigPanel) are removed by CSS type selector string, not by class reference. This is necessary because `importlib.reload()` replaces class objects, making `isinstance(old_widget, new_class)` return `False`.
