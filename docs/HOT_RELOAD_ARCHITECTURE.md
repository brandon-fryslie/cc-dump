# Hot-Reload Architecture

This document describes the hot-reload system in cc-dump, which enables real-time code updates without restarting the proxy server or losing TUI state.

## Overview

The hot-reload system allows you to modify formatting, rendering, and widget code while the proxy is running. Changes take effect immediately - the TUI updates to use the new code without losing accumulated data (conversation history, statistics, etc.).

**Key Principle**: Code modules are reloadable, but live object instances (the running HTTP server, the Textual app) are stable boundaries that never reload.

**Design Choice**: Any file change triggers a full reload of all reloadable modules plus widget replacement. This is intentional — the reload is fast and eliminates complexity from partial-reload logic.

**Two-file split**: Module classification and reload execution live in `app/hot_reload.py`. Widget replacement and file-watcher coordination live in `tui/hot_reload_controller.py`.

## Module Categories

All code modules fall into one of three categories:

### 1. Stable Boundary (NEVER reload)

These modules contain live instances or entry points that cannot be safely reloaded at runtime. They are split across two sets in `app/hot_reload.py`:

**Excluded files** (`_EXCLUDED_FILES`):

| Module | Reason |
|--------|--------|
| `pipeline/proxy.py` | HTTP server thread, must stay running |
| `pipeline/forward_proxy_tls.py` | Holds crypto state |
| `pipeline/event_types.py` | Stable type definitions |
| `pipeline/response_assembler.py` | Imported by proxy.py |
| `app/tmux_controller.py` | Holds live pane refs |
| `io/stderr_tee.py` | Holds live sys.stderr ref |
| `cli.py` | Entry point, already executed |
| `app/hot_reload.py` | The reloader itself |
| `__init__.py` / `__main__.py` | Module init / entry point |

**Excluded modules** (`_EXCLUDED_MODULES`):

| Module | Reason |
|--------|--------|
| `tui/app.py` | Live Textual App instance, holds widget references |
| `tui/hot_reload_controller.py` | Accesses live app/widget state for replacement |

**Critical Rule**: Stable boundary modules MUST use module-level imports for all reloadable code:

```python
# CORRECT - module-level import in stable boundary
import cc_dump.core.formatting
import cc_dump.tui.widget_factory

def handler():
    block = cc_dump.core.formatting.format_request(...)
    widget = cc_dump.tui.widget_factory.create_conversation_view()
```

```python
# WRONG - direct import creates stale reference
from cc_dump.core.formatting import format_request
from cc_dump.tui.widget_factory import create_conversation_view

def handler():
    block = format_request(...)  # STALE - won't update on hot-reload!
    widget = create_conversation_view()  # STALE
```

**Note**: The hot-reload system includes an alias-refresh pass (`_refresh_top_level_import_aliases`) that attempts to fix stale `from ... import` bindings across all loaded `cc_dump.*` modules after reload. This is a safety net, not a license to use `from` imports in stable boundaries.

### 2. Reloadable (Always reload on change)

These modules contain pure functions and class definitions. They can be safely reloaded because:
- They don't hold long-lived state
- They're imported via module references from stable boundaries
- They're reloaded in dependency order

The authoritative list is `_RELOAD_ORDER` in `app/hot_reload.py` (currently 64 modules). A representative subset:

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

1. **Create the module** in `src/cc_dump/core/`, `src/cc_dump/tui/`, `src/cc_dump/app/`, or `src/cc_dump/pipeline/`
2. **Update reload order** in `app/hot_reload.py:_RELOAD_ORDER`:
   - If it has no project dependencies, add it near the top
   - If it depends on other reloadable modules, add it after them
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
- Check that stable boundaries use `import module`, not `from module import func`
- The alias-refresh pass will catch many cases, but module-level imports are the correct fix

**Widget State Lost?**
- Verify `get_state()` returns all critical data
- Verify `restore_state()` handles missing keys with defaults
- Check that `replace_all_widgets()` in `tui/hot_reload_controller.py` processes your widget

**Type Errors?**
- Ensure widgets implement `get_state()` and `restore_state()` -- `validate_widget_protocol()` will catch missing methods at runtime

## Import Validation

The test `test_hot_reload.py::TestHotReloadIntegration::test_reloadable_modules_prefer_top_level_from_imports` enforces that certain reloadable modules use `from ... import` style (not bare `import cc_dump.X`) for intra-project dependencies, since reloadable modules are themselves reloaded and can use direct imports.

**Stable boundary** modules (in `_EXCLUDED_FILES` / `_EXCLUDED_MODULES`) should use module-level `import cc_dump.X` to avoid stale references.

## Design Rationale

### Why Module-Level Imports?

When you write `from module import func`, Python binds `func` to the function object at import time. Even if the module is reloaded, the old binding remains. Module-level imports (`import module`) keep a reference to the module object itself, which gets updated on reload.

### Why Widget Hot-Swap Instead of Instance Reload?

We can't "reload" a widget instance - it's a live object with Textual internals. Instead, we:
1. Extract state from the old instance
2. Create a new instance from the reloaded class
3. Transfer state to the new instance
4. Swap it in the DOM

This guarantees the new code is used while preserving user-visible state.

### Why Dependency Order?

If module A depends on module B, and B is reloaded first, A still has references to old B definitions. Reloading A after B ensures A gets the new B definitions.

### Why Exclude proxy.py and app.py?

- `pipeline/proxy.py` is running an HTTP server thread. Reloading it would kill the server.
- `tui/app.py` is the Textual app instance. Reloading it would destroy the entire UI.

Both are stable boundaries that orchestrate reloadable code via module references.

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

1. **Stable boundaries never reload** - they use module references to access reloadable code
2. **Reloadable modules reload in dependency order** - dependents after dependencies
3. **Widgets hot-swap via state transfer** - old instance state dict transferred to new instance

Follow the import patterns, implement the protocol, and your code will be instantly reloadable without losing state.
