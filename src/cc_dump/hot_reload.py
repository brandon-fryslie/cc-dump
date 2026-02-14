"""Hot-reload watcher for non-proxy modules.

This module monitors Python source files and reloads them when changes are detected.
Only pure-function modules are reloaded (formatting, rendering, analysis, colors).
Live instances (tui/app.py) and stable boundaries (proxy.py) are never reloaded.
"""

import importlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path

# Modules to reload in dependency order (leaves first, dependents after)
_RELOAD_ORDER = [
    "cc_dump.palette",  # no deps within project, base for all colors
    "cc_dump.tui.input_modes",  # no deps within project, pure data
    "cc_dump.colors",  # depends on: palette
    "cc_dump.analysis",  # no deps within project
    "cc_dump.formatting",  # depends on: colors, analysis
    "cc_dump.segmentation",  # depends on: nothing (pure parser, before rendering)
    "cc_dump.router",  # depends on: nothing within reloadable set
    "cc_dump.tui.search",  # depends on: palette
    "cc_dump.tui.rendering",  # depends on: formatting, colors
    "cc_dump.tui.custom_footer",  # depends on: palette, rendering
    "cc_dump.tui.panel_renderers",  # depends on: analysis
    "cc_dump.tui.event_handlers",  # depends on: analysis, formatting
    "cc_dump.tui.info_panel",  # depends on: palette, panel_renderers
    "cc_dump.tui.keys_panel",  # depends on: panel_renderers
    "cc_dump.tui.settings_panel",  # depends on: palette
    "cc_dump.tui.widget_factory",  # depends on: analysis, rendering, panel_renderers
]

# Files to explicitly exclude from watching
_EXCLUDED_FILES = {
    "proxy.py",  # stable boundary, never reload
    "cli.py",  # entry point, not reloadable at runtime
    "hot_reload.py",  # this file
    "event_types.py",  # stable type definitions, never reload
    "tmux_controller.py",  # stable boundary, holds live pane refs
    "__init__.py",  # module init
    "__main__.py",  # entry point
}

# Directories/modules to exclude
_EXCLUDED_MODULES = {
    "tui/app.py",  # live app instance, can't safely reload
    "tui/category_config.py",  # pure data, but referenced at init time
    "tui/action_handlers.py",  # accesses live app/widget state
    "tui/search_controller.py",  # accesses live app/widget state
    "tui/dump_export.py",  # accesses live app/widget state
    "tui/theme_controller.py",  # accesses live app/widget state
    "tui/hot_reload_controller.py",  # accesses live app/widget state
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


def _iter_watched_files() -> Iterator[tuple[str, str]]:
    """Yield (abs_path, rel_path) for all watched Python files after exclusion filters."""
    root = Path(_watch_dirs[0]) if _watch_dirs else None
    for d in _watch_dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.endswith(".py") or fname in _EXCLUDED_FILES:
                continue
            abs_path = os.path.join(d, fname)
            rel_str = str(Path(abs_path).relative_to(root)).replace(os.sep, "/")
            if rel_str in _EXCLUDED_MODULES:
                continue
            yield abs_path, rel_str


def has_changes() -> bool:
    """Check if any watched files have changed mtimes (without updating cache).

    Cheap read-only scan — no module reloads, no side effects on _mtimes.
    Use this for debounce detection; call check_and_get_reloaded() to actually reload.
    """
    for abs_path, _rel in _iter_watched_files():
        try:
            mtime = os.path.getmtime(abs_path)
            if abs_path not in _mtimes or _mtimes[abs_path] != mtime:
                return True
        except (FileNotFoundError, OSError):
            pass
    return False


def check() -> bool:
    """Check for file changes and reload if necessary.

    Returns:
        True if any module was reloaded, False otherwise.
    """
    return bool(check_and_get_reloaded())


def check_and_get_reloaded() -> list[str]:
    """Check for file changes and reload if necessary.

    Returns:
        List of module names that were reloaded, empty if none.
    """
    changed_files = _get_changed_files()
    if not changed_files:
        return []

    # Log what changed
    for path in changed_files:
        print(f"[hot-reload] detected change: {path}", file=sys.stderr)

    # Reload all modules in dependency order — any file change triggers full reload
    to_reload = list(_RELOAD_ORDER)

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
        print(
            f"[hot-reload] reloaded {len(reloaded)} module(s): {', '.join(reloaded)}",
            file=sys.stderr,
        )

    return reloaded


def _scan_mtimes() -> None:
    """Populate mtime cache with current file modification times."""
    for abs_path, _rel in _iter_watched_files():
        try:
            _mtimes[abs_path] = os.path.getmtime(abs_path)
        except FileNotFoundError:
            pass  # File deleted between listdir and getmtime
        except OSError as e:
            sys.stderr.write(f"[hot-reload] cannot stat {abs_path}: {e}\n")
            sys.stderr.flush()


def _get_changed_files() -> set[str]:
    """Return set of files with changed mtimes since last check.

    Returns:
        Set of absolute file paths that have changed.
    """
    changed = set()
    for abs_path, _rel in _iter_watched_files():
        try:
            mtime = os.path.getmtime(abs_path)
            if abs_path not in _mtimes or _mtimes[abs_path] != mtime:
                changed.add(abs_path)
            _mtimes[abs_path] = mtime
        except FileNotFoundError:
            pass  # File deleted between listdir and getmtime
        except OSError as e:
            sys.stderr.write(f"[hot-reload] cannot stat {abs_path}: {e}\n")
            sys.stderr.flush()

    return changed
