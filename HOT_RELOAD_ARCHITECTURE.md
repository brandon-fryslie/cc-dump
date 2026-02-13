# Hot-Reload Architecture

This document describes the hot-reload system in cc-dump, which enables real-time code updates without restarting the proxy server or losing TUI state.

## Overview

The hot-reload system allows you to modify formatting, rendering, and widget code while the proxy is running. Changes take effect immediately - the TUI updates to use the new code without losing accumulated data (conversation history, statistics, etc.).

**Key Principle**: Code modules are reloadable, but live object instances (the running HTTP server, the Textual app) are stable boundaries that never reload.

**Design Choice**: Any file change triggers a full reload of all reloadable modules plus widget replacement. This is intentional — the reload is fast and eliminates complexity from partial-reload logic.

## Module Categories

All code modules fall into one of three categories:

### 1. Stable Boundary (NEVER reload)

These modules contain live instances or entry points that cannot be safely reloaded at runtime.

| Module | Reason | Import Pattern |
|--------|--------|----------------|
| `proxy.py` | HTTP server thread, must stay running | Use `import module` only |
| `cli.py` | Entry point, already executed | N/A |
| `hot_reload.py` | The reloader itself | N/A |
| `tui/app.py` | Textual App instance, holds widget references | Use `import module` only |
| `tui/widgets.py` | Shim holding current widget instances | Use `import module` only |

**Critical Rule**: Stable boundary modules MUST use module-level imports for all reloadable code:

```python
# CORRECT - module-level import in stable boundary
import cc_dump.formatting
import cc_dump.tui.widget_factory

def handler():
    block = cc_dump.formatting.format_request(...)
    widget = cc_dump.tui.widget_factory.create_conversation_view()
```

```python
# WRONG - direct import creates stale reference
from cc_dump.formatting import format_request
from cc_dump.tui.widget_factory import create_conversation_view

def handler():
    block = format_request(...)  # STALE - won't update on hot-reload!
    widget = create_conversation_view()  # STALE
```

### 2. Reloadable (Always reload on change)

These modules contain pure functions and class definitions. They can be safely reloaded because:
- They don't hold long-lived state
- They're imported via module references from stable boundaries
- They're reloaded in dependency order

| Module | Dependencies | Purpose |
|--------|--------------|---------|
| `colors.py` | (none) | Color scheme definitions |
| `analysis.py` | (none) | Request/response analysis functions |
| `tui/protocols.py` | (none) | Protocol definitions for hot-swappable widgets |
| `router.py` | (none) | Request routing / event fan-out |
| `formatting.py` | colors, analysis | Format requests/responses to structured blocks |
| `tui/rendering.py` | formatting, colors | Render blocks to Rich Text objects |
| `tui/panel_renderers.py` | analysis | Render stats/economics/timeline panels |
| `tui/event_handlers.py` | analysis, formatting | Event processing logic |
| `tui/widget_factory.py` | analysis, rendering, panel_renderers, protocols | Widget class definitions and factory functions |

**Reload Order**: Modules reload in dependency order (leaves first, dependents after). See `hot_reload.py:_RELOAD_ORDER` for the authoritative list.

## Widget Hot-Swap Pattern

The most sophisticated part of hot-reload is widget hot-swapping. When `widget_factory.py` is reloaded, the TUI replaces all widget instances with fresh ones created from the new class definitions.

### How It Works

1. **File Change Detected**: `hot_reload.py` detects a change to `widget_factory.py`
2. **Module Reloaded**: The module is reloaded via `importlib.reload()`
3. **State Extraction**: App calls `get_state()` on each old widget instance
4. **New Instances Created**: App calls factory functions to create new instances (using reloaded classes)
5. **State Restoration**: App calls `restore_state(state)` on each new widget
6. **DOM Swap**: App removes old widgets and mounts new ones in the same positions
7. **Re-render**: Conversation view re-renders with new rendering code

### HotSwappableWidget Protocol

All widgets that can be hot-swapped must implement the `HotSwappableWidget` protocol:

```python
from typing import Protocol, Dict, Any

class HotSwappableWidget(Protocol):
    """Protocol for widgets that can be hot-swapped at runtime."""

    def get_state(self) -> Dict[str, Any]:
        """Extract widget state for transfer to a new instance."""
        ...

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from a previous instance."""
        ...
```

The protocol uses structural typing (duck typing with type safety), so widgets don't need to explicitly inherit from it.

### Widget State Examples

Each widget defines what state it needs to preserve across hot-swaps:

**ConversationView** (conversation history + streaming state):
```python
def get_state(self) -> dict:
    return {
        "all_blocks": [td.blocks for td in self._turns],
        "follow_mode": self._follow_mode,
        "turn_count": len(self._turns),
        "streaming_states": [...],  # active streaming turn deltas
    }

def restore_state(self, state: dict):
    self._pending_restore = state
    self._follow_mode = state.get("follow_mode", True)
```

**StatsPanel** (accumulated statistics):
```python
def get_state(self) -> dict:
    return {
        "request_count": self.request_count,
        "models_seen": set(self.models_seen),
    }

def restore_state(self, state: dict):
    self.request_count = state.get("request_count", 0)
    self.models_seen = state.get("models_seen", set())
```

## Developer Workflows

### How to Add a New Reloadable Module

1. **Create the module** in `src/cc_dump/` or `src/cc_dump/tui/`
2. **Update reload order** in `hot_reload.py:_RELOAD_ORDER`:
   - If it has no project dependencies, add it near the top
   - If it depends on other reloadable modules, add it after them
3. **Test the reload**: Make a change and verify it reloads without errors

Example:
```python
# In hot_reload.py
_RELOAD_ORDER = [
    "cc_dump.colors",
    "cc_dump.analysis",
    "cc_dump.tui.protocols",
    "cc_dump.your_new_module",  # <-- Add here if it depends on analysis
    "cc_dump.formatting",
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

2. **Add a factory function** with protocol return type:
   ```python
   def create_my_widget() -> cc_dump.tui.protocols.HotSwappableWidget:
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

4. **Add to hot-swap logic in app.py** (`_replace_all_widgets` method):
   ```python
   def _replace_all_widgets(self):
       # Extract state
       my_state = self._get_my_widget().get_state()

       # Create new instance
       new_widget = cc_dump.tui.widget_factory.create_my_widget()
       new_widget.id = "my-widget"
       new_widget.restore_state(my_state)

       # Swap in DOM
       old_widget = self._get_my_widget()
       old_widget.remove()
       self.mount(new_widget, after=...)
   ```

### How to Debug Hot-Reload Issues

**Module Not Reloading?**
- Check that it's in `_RELOAD_ORDER` in `hot_reload.py`
- Check that it's not in `_EXCLUDED_FILES` or `_EXCLUDED_MODULES`
- Watch stderr for `[hot-reload]` messages

**Stale References?**
- Check that stable boundaries use `import module`, not `from module import func`
- Use the import validation test (see below)

**Widget State Lost?**
- Verify `get_state()` returns all critical data
- Verify `restore_state()` handles missing keys with defaults
- Check that `_replace_all_widgets()` calls both methods

**Type Errors?**
- Ensure factory functions return `HotSwappableWidget` protocol type
- Run `mypy` or `pyright` to check protocol compliance

## Import Validation

To catch stale reference bugs early, run the import validation test:

```bash
uv run pytest tests/test_hot_reload.py::test_import_validation -v
```

This test scans stable boundary modules (`app.py`, `proxy.py`) for forbidden `from ... import` patterns that would create stale references to reloadable code.

**Forbidden Patterns** (in stable boundaries):
```python
from cc_dump.formatting import format_request  # FORBIDDEN
from cc_dump.tui.widget_factory import create_conversation_view  # FORBIDDEN
```

**Required Patterns** (in stable boundaries):
```python
import cc_dump.formatting  # REQUIRED
import cc_dump.tui.widget_factory  # REQUIRED

# Use fully-qualified calls:
block = cc_dump.formatting.format_request(...)
widget = cc_dump.tui.widget_factory.create_conversation_view()
```

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

- `proxy.py` is running an HTTP server thread. Reloading it would kill the server.
- `app.py` is the Textual app instance. Reloading it would destroy the entire UI.

Both are stable boundaries that orchestrate reloadable code via module references.

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

## Future Enhancements

Potential improvements to the hot-reload system:

1. **Automated Dependency Ordering**: Use AST analysis to compute reload order automatically.
2. **State Versioning**: Support schema evolution in widget state (handle added/removed fields gracefully).
3. **CI Integration**: Run import validation on every commit to prevent stale reference bugs.
4. **Persistent State**: Serialize widget state to disk for cross-restart preservation.
5. **Partial Reloads**: Reload only changed functions within a module (advanced, fragile).

## Summary

The hot-reload system is built on three principles:

1. **Stable boundaries never reload** - they use module references to access reloadable code
2. **Reloadable modules reload in dependency order** - dependents after dependencies
3. **Widgets hot-swap via state transfer** - old instance → state dict → new instance

Follow the import patterns, implement the protocol, and your code will be instantly reloadable without losing state.
