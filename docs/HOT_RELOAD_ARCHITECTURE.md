# Hot-Reload Architecture

This document describes the hot-reload system in cc-dump, which enables real-time code updates without restarting the proxy server or losing TUI state.

## Overview

The hot-reload system allows you to modify formatting, rendering, and widget code while the proxy is running. Changes take effect immediately - the TUI updates to use the new code without losing accumulated data (conversation history, statistics, etc.).

**Key Principle**: Code modules are reloadable, but live object instances (the running HTTP server, the Textual app) are stable boundaries that never reload.

**Design Choice**: Any file change triggers a full reload of all reloadable modules plus widget replacement. This is intentional — the reload is fast and eliminates complexity from partial-reload logic.

**Two-file split**: Module classification and reload execution live in `app/hot_reload.py`. Widget replacement and file-watcher coordination live in `tui/hot_reload_controller.py`.

## Module Categories

Every module reloads by default. A module is stable only for one of four reasons, listed below.

### 1. Stable Boundary (NEVER reload)

A module stays stable only if reloading it would break the live session. There are exactly four reasons for that, and every stable entry is one of them:

- **Live instance.** The module *is* a running object that can't be recreated in place — the HTTP proxy server thread or the Textual App. Reloading it would kill the server or destroy the UI.
- **Entry point.** The module already executed and isn't meaningful to re-run at runtime (`cli.py`, `__main__.py`, the reloader itself).
- **H1 — boundary-crossing type.** The module defines a class the stable proxy instantiates and other code `isinstance`-checks. `importlib.reload` gives the class a new identity, so an object built before the reload no longer matches the reloaded class and the check silently returns False.
- **H2 — module-level live state.** The module holds a module-level mutable singleton that other live objects reference. Reload re-runs the module body and resets that singleton, leaving old holders pointed at the pre-reload copy — split-brain.

H1 and H2 are the *only* reasons to make a boundary module stable; a module with neither hazard that isn't itself a live instance or entry point reloads. The stable modules split across two sets in `app/hot_reload.py`, each entry carrying its reason as an inline comment.

**Excluded files** (`_EXCLUDED_FILES`):

| Module | Reason | Why |
|--------|--------|-----|
| `pipeline/proxy.py` | live instance | HTTP server thread serving the current session |
| `pipeline/response_assembler.py` | live instance | Imported and driven by the running proxy |
| `pipeline/event_types.py` | H1 | Boundary types the proxy builds and other code `isinstance`-checks |
| `pipeline/proxy_call.py` | H1 + H2 | `proxy.py` does `isinstance(planned, RefusedCall)`; also holds the live `RequestPipeline` from `cli.py` |
| `pipeline/forward_proxy_tls.py` | H2 | Holds live TLS/crypto state |
| `pipeline/copilot_translate.py` | H2 | Proxy drives a live SSE parser / translation state across an in-flight stream |
| `providers.py` | H2 | `_PROVIDERS` registry mutated at runtime by `--upstream`, read on the proxy path |
| `io/logging_setup.py` | H2 | `_RUNTIME` guards global logging handlers; reload loses the log path and risks double-attach |
| `app/tmux_controller.py` | H2 | Holds live tmux pane references |
| `io/stderr_tee.py` | H2 | Holds the live `sys.stderr` reference |
| `cli.py` | entry point | Already executed; not re-runnable at runtime |
| `app/hot_reload.py` | entry point | The reloader itself |
| `__init__.py` / `__main__.py` | entry point | Package init / entry point |

**Excluded modules** (`_EXCLUDED_MODULES`):

| Module | Reason | Why |
|--------|--------|-----|
| `tui/app.py` | live instance | The running Textual App; holds every widget reference |
| `tui/hot_reload_controller.py` | live instance | Drives the swap; accesses live app/widget state |

**Import spelling doesn't matter.** After every reload, `_refresh_top_level_import_aliases` walks all loaded `cc_dump.*` modules and rebinds any stale `from x import y` alias to the reloaded object, so a stable boundary can import reloadable code either way. An earlier version of this doc required `import cc_dump.x` over `from cc_dump.x import y`; that rule was moot and has been removed. The pass rebinds functions and classes but skips plain data exports (ints, strings, dicts, sets) — not a real gap, because any reloadable module exporting module-level mutable state for others to hold would itself be an H2 stable module.

### 2. Reloadable (Always reload on change)

Everything without an H1 or H2 hazard — and that isn't a live instance or entry point — is reloadable, which is the large majority of the codebase: formatting, rendering, the panels and widgets, the analytics store, the HAR recorder/replayer, the registries.

**Honesty caveat.** Reloading refreshes a module's code, but a live instance the App or a widget already holds keeps its old methods until it is re-created — `importlib.reload` redefines the class, yet existing objects still point at the old one. The widget hot-swap (below) re-instantiates widgets so they pick up new methods; a singleton the App merely holds gets new module-level code but not new instance methods until a restart or swap. Reloading it is still safe — strictly better than the previous silent no-op — it just doesn't fully take effect on the held instance.

The authoritative list is `_RELOAD_ORDER` in `app/hot_reload.py`. A representative subset:

| Module | Dependencies | Purpose |
|--------|--------------|---------|
| `core/filter_registry.py` | (none) | Canonical filter/category registry |
| `core/palette.py` | (none) | Base for all colors |
| `core/analysis.py` | (none) | Request/response analysis functions |
| `tui/protocols.py` | (none) | Protocol definitions for hot-swappable widgets |
| `core/formatting_impl.py` | palette, analysis | Format implementation |
| `core/formatting.py` | formatting_impl | Formatting facade |
| `pipeline/router.py` | (none) | Request routing / event fan-out |
| `tui/rendering_impl.py` | formatting, palette | Rendering implementation |
| `tui/rendering.py` | rendering_impl | Rendering facade |
| `tui/panel_renderers.py` | analysis | Render stats/economics/timeline panels |
| `tui/event_handlers.py` | analysis, formatting | Event processing logic |
| `tui/widget_factory.py` | analysis, rendering, panel_renderers, error_indicator | Widget class definitions and factory functions |
| `tui/action_handlers.py` | formatting, action_config, rendering, widget_factory | Action handling |
| `tui/custom_footer.py` | chip, palette, rendering, store_widget, follow_mode | Footer widget |

**Reload Order**: Modules reload in dependency order (leaves first, dependents after). See `app/hot_reload.py:_RELOAD_ORDER` for the authoritative list.

## Widget Hot-Swap Pattern

The most sophisticated part of hot-reload is widget hot-swapping. When any reloadable module changes, all modules are reloaded and the TUI replaces all widget instances with fresh ones created from the new class definitions.

### How It Works

1. **File Change Detected**: `tui/hot_reload_controller.py` runs a `watchfiles.awatch()` loop; changes to reloadable files are debounced (2s quiet period)
2. **Modules Reloaded**: `app/hot_reload.py:check_and_get_reloaded()` reloads all modules in `_RELOAD_ORDER` via `importlib.reload()`
3. **State Captured**: `_capture_widget_snapshot()` calls `get_state()` on each old widget (conversations, panels, logs, info, footer)
4. **New Instances Created**: `_build_replacement_*()` functions call factory functions to create new instances from reloaded classes
5. **Protocol Validated**: Each new widget is checked against `HotSwappableWidget` protocol before state restore
6. **State Restored**: `restore_state(state)` called on each new widget
7. **DOM Swap**: Old widgets removed, new widgets mounted in deterministic order
8. **Re-render**: Conversation views re-render with new rendering code

### HotSwappableWidget Protocol

All widgets that can be hot-swapped must implement the `HotSwappableWidget` protocol (defined in `tui/protocols.py`):

```python
from typing import Protocol, runtime_checkable

_Leaf = str | int | float | bool | None
WidgetStateValue = _Leaf | list | dict | set
WidgetState = dict[str, WidgetStateValue]

@runtime_checkable
class HotSwappableWidget(Protocol):
    """Protocol for widgets that can be hot-swapped at runtime."""

    def get_state(self) -> WidgetState:
        """Extract widget state for transfer to a new instance."""
        ...

    def restore_state(self, state: WidgetState) -> None:
        """Restore state from a previous instance."""
        ...
```

The protocol uses structural typing (duck typing with type safety), so widgets don't need to explicitly inherit from it. It is `@runtime_checkable` and validated at swap time via `validate_widget_protocol()`.

### Widget State Examples

Each widget defines what state it needs to preserve across hot-swaps:

**ConversationView** (view/rendering state only -- domain data lives in `DomainStore`):
```python
def get_state(self) -> dict:
    return {
        "follow_state": self._follow_state.value,
        "scroll_anchor": anchor_dict,
        "view_overrides": self._view_overrides.to_dict(),
    }
```

**StatsPanel** (current view mode):
```python
def get_state(self) -> dict:
    return {"view_index": self._view_index}
```

## Developer Workflows

### How to Add a New Reloadable Module

1. **Create the module** in `src/cc_dump/core/`, `src/cc_dump/tui/`, `src/cc_dump/app/`, or `src/cc_dump/pipeline/`. Reloadable is the default — you only make it stable if it has an H1 or H2 hazard.
2. **Add it to `_RELOAD_ORDER`** in `app/hot_reload.py`. Place it after its dependencies (leaves first). Ordering rarely affects correctness — the alias-refresh pass heals references regardless — but see "Why Dependency Order?" for the one exception (import-time-computed values). Skipping this step fails the completeness gate in CI, so it can't be silently forgotten.
3. **Test the reload**: Make a change and verify it reloads without errors

Example:
```python
# In app/hot_reload.py
_RELOAD_ORDER = [
    "cc_dump.core.filter_registry",
    "cc_dump.core.palette",
    "cc_dump.tui.input_modes",
    "cc_dump.core.analysis",
    "cc_dump.your_new_module",  # <-- Add here if it depends on analysis
    "cc_dump.core.formatting_impl",
    # ...
]
```

### How to Add a New Widget

1. **Define the widget class** in `tui/widget_factory.py`:
   ```python
   class MyNewWidget(Static):
       def __init__(self):
           super().__init__("")
           self._my_data = []

       def get_state(self) -> dict:
           return {"my_data": self._my_data}

       def restore_state(self, state: dict):
           self._my_data = state.get("my_data", [])
   ```

2. **Add a factory function**:
   ```python
   def create_my_widget() -> MyNewWidget:
       return MyNewWidget()
   ```

3. **Use the factory in app.py** (module-level import):
   ```python
   import cc_dump.tui.widget_factory

   # In compose():
   widget = cc_dump.tui.widget_factory.create_my_widget()
   widget.id = "my-widget"
   yield widget
   ```

4. **Add to hot-swap logic** in `tui/hot_reload_controller.py` -- the `replace_all_widgets()` function handles the full swap cycle (capture snapshot, build replacements, remove old, mount new).

### How to Debug Hot-Reload Issues

**Module Not Reloading?**
- Check that it's in `_RELOAD_ORDER` in `app/hot_reload.py`
- Check that it's not in `_EXCLUDED_FILES` or `_EXCLUDED_MODULES`
- Watch stderr for `[hot-reload]` messages

**Stale References?**
- The alias-refresh pass rebinds `from ... import` aliases after every reload, so stale function/class references heal automatically — import spelling is not the cause.
- If behavior still looks stale, it's almost always a live instance holding old methods (see the honesty caveat under Reloadable). Restart or trigger a widget swap.

**Widget State Lost?**
- Verify `get_state()` returns all critical data
- Verify `restore_state()` handles missing keys with defaults
- Check that `replace_all_widgets()` in `tui/hot_reload_controller.py` processes your widget

**Type Errors?**
- Ensure widgets implement `get_state()` and `restore_state()` -- `validate_widget_protocol()` will catch missing methods at runtime

## Classification Enforcement

Every module must be classified reloadable (in `_RELOAD_ORDER`) or stable (in `_EXCLUDED_FILES` / `_EXCLUDED_MODULES`). `unclassified_modules()` in `app/hot_reload.py` walks the package and returns any in-scope module in neither set; `scripts/quality_gate.py` and `test_hot_reload.py` both fail on a non-empty result. This closes the drift that once left 36 modules silently unreloaded and off the staleness watchlist — a new module now fails CI until you classify it.

A separate style test, `test_reloadable_modules_prefer_top_level_from_imports`, keeps a few reloadable modules on `from ... import`. It is cosmetic only: the alias-refresh pass means import spelling has no effect on reload correctness either way.

## Design Rationale

### Why Import Spelling Doesn't Matter

`from module import func` binds `func` to the function object at import time, so a naive reload would leave that old binding in place. cc-dump handles it with the alias-refresh pass: after every reload it rebinds those stale aliases to the reloaded objects across all loaded `cc_dump.*` modules. That is why there is no rule about `import module` versus `from module import func` — either works.

### Why Widget Hot-Swap Instead of Instance Reload?

We can't "reload" a widget instance - it's a live object with Textual internals. Instead, we:
1. Extract state from the old instance
2. Create a new instance from the reloaded class
3. Transfer state to the new instance
4. Swap it in the DOM

This guarantees the new code is used while preserving user-visible state.

### Why Dependency Order?

Mostly readability. `_RELOAD_ORDER` lists leaves before dependents so it reads as a dependency graph, and the alias-refresh pass rebinds function and class references across all modules after the reload completes, so for ordinary code a wrong order costs nothing but legibility. The one exception is a module that computes a module-level value from a dependency at import time (`MY_VAL = dependency.compute()`): reload re-runs that line, and if the dependency hasn't reloaded yet the value captures the old result. The alias pass can't fix it — a freshly computed value was never one of the dependency's exports, and if it's a scalar or container the pass skips it anyway. No current reloadable module has this pattern, so ordering is effectively free today; keep placing new modules after their dependencies so it stays that way.

### Why Exclude proxy.py and app.py?

- `pipeline/proxy.py` is running an HTTP server thread. Reloading it would kill the server.
- `tui/app.py` is the Textual app instance. Reloading it would destroy the entire UI.

Both are live instances — the "live instance" reason in the decision procedure above.

## Staleness Detection

Excluded files that developers might edit are tracked in `_STALENESS_WATCHLIST`. On each file change event, `get_stale_excluded()` compares content hashes against startup snapshots. If an excluded file has changed, it's reported as "stale" in the UI -- the user needs to restart to pick up those changes.

## Troubleshooting

### Notification Says "reloaded" But Code Didn't Change

- You may be hitting a cached `.pyc` file. The module reloaded, but the source didn't change.
- Check the file's mtime to confirm the save went through.

### Widget Displays Old Content After Swap

- Verify `restore_state()` is calling `_refresh_display()` or equivalent.
- Check that the rendering functions are in reloadable modules.

### Import Error After Reload

- A module failed to reload due to syntax or import error.
- Check stderr for the error message.
- Fix the error and save again - reload will retry.

### Proxy Crashed After Hot-Reload

- This should never happen. If it does, there's a bug in the reload system.
- Check if a stable boundary was accidentally reloaded.
- File an issue with the error traceback.

## Summary

The hot-reload system is built on three principles:

1. **A module reloads unless reloading it breaks the live session** — the running proxy and App, boundary-crossing types (H1), and module-level live state (H2) stay stable; everything else reloads.
2. **Reload order rarely matters** — the alias-refresh pass heals references globally, so `_RELOAD_ORDER` is ordered leaves-first mainly for readability; order affects correctness only for a module that computes a value from a dependency at import time (see "Why Dependency Order?").
3. **Widgets hot-swap via state transfer** — old-instance state is captured and restored onto a fresh instance built from the reloaded class.

Classify new modules reloadable-or-stable (the completeness gate enforces it), implement the widget protocol, and your code reloads without losing state.
