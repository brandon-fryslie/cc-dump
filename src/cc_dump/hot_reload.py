"""Hot-reload watcher for non-proxy modules.

This module monitors Python source files and reloads them when changes are detected.
Only pure-function modules are reloaded (formatting, rendering, analysis, colors).
Live instances (tui/app.py, tui/widgets.py) and stable boundaries (proxy.py) are never reloaded.
"""

import importlib
import os
import sys
from pathlib import Path

# Modules to reload in dependency order (leaves first, dependents after)
_RELOAD_ORDER = [
    "cc_dump.colors",      # no deps within project
    "cc_dump.analysis",    # no deps within project
    "cc_dump.formatting",  # depends on: colors, analysis
    "cc_dump.tui.rendering",  # depends on: formatting, colors
]

# Additional modules reloaded only if they themselves changed
_RELOAD_IF_CHANGED = [
    "cc_dump.schema",
    "cc_dump.store",
    "cc_dump.router",
]

# Files to explicitly exclude from watching
_EXCLUDED_FILES = {
    "proxy.py",      # stable boundary, never reload
    "cli.py",        # entry point, not reloadable at runtime
    "hot_reload.py", # this file
    "__init__.py",   # module init
    "__main__.py",   # entry point
}

# Directories/modules to exclude
_EXCLUDED_MODULES = {
    "tui/app.py",     # live app instance, can't safely reload
    "tui/widgets.py", # live widget instances, can't safely reload
}

_watch_dirs: list[str] = []
_mtimes: dict[str, float] = {}


def init(package_dir: str) -> None:
    """Initialize watcher with the package source directory.

    Args:
        package_dir: Path to the cc_dump package directory (e.g., /path/to/src/cc_dump)
    """
    _watch_dirs.clear()
    _watch_dirs.append(package_dir)

    tui_dir = os.path.join(package_dir, "tui")
    if os.path.isdir(tui_dir):
        _watch_dirs.append(tui_dir)

    # Seed initial mtimes
    _scan_mtimes()


def check() -> bool:
    """Check for file changes and reload if necessary.

    Returns:
        True if any module was reloaded, False otherwise.
    """
    changed_files = _get_changed_files()
    if not changed_files:
        return False

    # Log what changed
    for path in changed_files:
        print(f"[hot-reload] detected change: {path}", file=sys.stderr)

    # Determine which modules to reload
    to_reload = list(_RELOAD_ORDER)  # always reload full display path if any changed

    # Add optional modules only if they themselves changed
    for mod_name in _RELOAD_IF_CHANGED:
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "__file__") and mod.__file__ in changed_files:
            to_reload.append(mod_name)

    # Reload in order
    reloaded = []
    for mod_name in to_reload:
        mod = sys.modules.get(mod_name)
        if mod:
            try:
                importlib.reload(mod)
                reloaded.append(mod_name)
            except Exception as e:
                print(f"[hot-reload] error reloading {mod_name}: {e}", file=sys.stderr)
                # Continue with other modules even if one fails
                # This way a syntax error in one module doesn't break the whole reload

    if reloaded:
        print(f"[hot-reload] reloaded {len(reloaded)} module(s): {', '.join(reloaded)}", file=sys.stderr)
        return True

    return False


def _scan_mtimes() -> None:
    """Populate mtime cache with current file modification times."""
    for d in _watch_dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.endswith(".py"):
                continue
            if fname in _EXCLUDED_FILES:
                continue

            path = os.path.join(d, fname)
            # Check if this is an excluded module
            rel_path = Path(path).relative_to(Path(_watch_dirs[0]).parent)
            rel_str = str(rel_path).replace(os.sep, "/")
            if any(excl in rel_str for excl in _EXCLUDED_MODULES):
                continue

            try:
                _mtimes[path] = os.path.getmtime(path)
            except OSError:
                # File may have been deleted or is inaccessible
                pass


def _get_changed_files() -> set[str]:
    """Return set of files with changed mtimes since last check.

    Returns:
        Set of absolute file paths that have changed.
    """
    changed = set()
    for d in _watch_dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.endswith(".py"):
                continue
            if fname in _EXCLUDED_FILES:
                continue

            path = os.path.join(d, fname)
            # Check if this is an excluded module
            rel_path = Path(path).relative_to(Path(_watch_dirs[0]).parent)
            rel_str = str(rel_path).replace(os.sep, "/")
            if any(excl in rel_str for excl in _EXCLUDED_MODULES):
                continue

            try:
                mtime = os.path.getmtime(path)
                if path in _mtimes and _mtimes[path] != mtime:
                    changed.add(path)
                _mtimes[path] = mtime
            except OSError:
                # File may have been deleted or is inaccessible
                pass

    return changed
