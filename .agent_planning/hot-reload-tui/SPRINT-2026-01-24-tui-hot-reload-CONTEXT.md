# Implementation Context: tui-hot-reload

## Architecture Decision: What Gets Reloaded

The key insight is that `importlib.reload()` updates the module object in-place, but existing name bindings in other modules are NOT updated. There are two approaches:

### Approach A: Module-level access (recommended)
Change all call sites to use fully-qualified access:
```python
# Instead of:
from cc_dump.formatting import format_request
blocks = format_request(body, state)

# Use:
import cc_dump.formatting
blocks = cc_dump.formatting.format_request(body, state)
```

After `importlib.reload(cc_dump.formatting)`, the next call to `cc_dump.formatting.format_request` automatically uses the new code.

### Approach B: Re-import after reload
After reloading, re-bind names in the calling module. More complex, fragile.

**Decision: Use Approach A.** Refactor `tui/app.py` and `tui/widgets.py` to use module-level access for all reloadable functions.

## Reload Order (dependency graph, leaves first)

```
1. cc_dump.colors          (no deps within project)
2. cc_dump.analysis        (no deps within project)
3. cc_dump.formatting      (depends on: colors, analysis)
4. cc_dump.tui.rendering   (depends on: formatting, colors)
5. cc_dump.store           (depends on: analysis, schema — only if changed)
6. cc_dump.schema          (no deps — only if changed)
7. cc_dump.router          (no deps — only if changed)
```

Do NOT reload:
- `cc_dump.proxy` (stable boundary)
- `cc_dump.cli` (entry point, not reloadable at runtime)
- `cc_dump.tui.app` (running instance, can't safely reload)
- `cc_dump.tui.widgets` (live widget instances, can't safely reload)

## Where to Put the Watcher

Create `src/cc_dump/hot_reload.py`:
```python
"""Hot-reload watcher for non-proxy modules."""

import importlib
import os
import sys

# Modules to reload, in dependency order
_RELOAD_ORDER = [
    "cc_dump.colors",
    "cc_dump.analysis",
    "cc_dump.formatting",
    "cc_dump.tui.rendering",
]

# Additional modules reloaded only if they themselves changed
_RELOAD_IF_CHANGED = [
    "cc_dump.schema",
    "cc_dump.store",
    "cc_dump.router",
]

_watch_dirs = []  # populated on init
_mtimes: dict[str, float] = {}


def init(package_dir: str):
    """Initialize watcher with the package source directory."""
    _watch_dirs.clear()
    _watch_dirs.append(package_dir)
    tui_dir = os.path.join(package_dir, "tui")
    if os.path.isdir(tui_dir):
        _watch_dirs.append(tui_dir)
    # Seed mtimes
    _scan_mtimes()


def check() -> bool:
    """Check for changes. Returns True if any module was reloaded."""
    changed_files = _get_changed_files()
    if not changed_files:
        return False

    # Determine which modules to reload
    to_reload = list(_RELOAD_ORDER)  # always reload full display path
    for mod_name in _RELOAD_IF_CHANGED:
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "__file__") and mod.__file__ in changed_files:
            to_reload.append(mod_name)

    # Reload in order
    for mod_name in to_reload:
        mod = sys.modules.get(mod_name)
        if mod:
            try:
                importlib.reload(mod)
            except Exception as e:
                sys.stderr.write(f"[hot-reload] error reloading {mod_name}: {e}\n")
                return False

    return True


def _scan_mtimes():
    """Populate mtime cache."""
    for d in _watch_dirs:
        for fname in os.listdir(d):
            if fname.endswith(".py"):
                path = os.path.join(d, fname)
                _mtimes[path] = os.path.getmtime(path)


def _get_changed_files() -> set[str]:
    """Return set of files with changed mtimes since last check."""
    changed = set()
    for d in _watch_dirs:
        for fname in os.listdir(d):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(d, fname)
            mtime = os.path.getmtime(path)
            if path in _mtimes and _mtimes[path] != mtime:
                changed.add(path)
            _mtimes[path] = mtime
    return changed
```

## Integration Point in TUI

In `tui/app.py`'s `_drain_events` worker:

```python
def _drain_events(self):
    while not self._closing:
        try:
            event = self._event_queue.get(timeout=1.0)
        except queue.Empty:
            # Check for hot reload even when idle
            self.call_from_thread(self._check_hot_reload)
            continue

        # Check before processing
        self.call_from_thread(self._check_hot_reload)
        self.call_from_thread(self._handle_event, event)

def _check_hot_reload(self):
    import cc_dump.hot_reload
    if cc_dump.hot_reload.check():
        # Notify user
        self.notify("[hot-reload] modules reloaded", severity="information")
        # Re-render with new code
        self.query_one(ConversationView).rerender(self.active_filters)
```

## Refactoring tui/app.py imports

Change from:
```python
from cc_dump.formatting import format_request, format_response_event, ...
from cc_dump.analysis import TurnBudget, correlate_tools, ...
```

To:
```python
import cc_dump.formatting
import cc_dump.analysis
```

Then access as `cc_dump.formatting.format_request(...)` etc. This ensures reload takes effect.

Similarly in `tui/widgets.py` — if it imports from `tui/rendering.py`, use module-level access.

## Files Modified

1. `src/cc_dump/hot_reload.py` — NEW: file watcher + reload logic
2. `src/cc_dump/tui/app.py` — Refactor imports to module-level access, add reload check
3. `src/cc_dump/tui/widgets.py` — Refactor imports if needed
4. `src/cc_dump/cli.py` — Initialize hot_reload watcher on startup
