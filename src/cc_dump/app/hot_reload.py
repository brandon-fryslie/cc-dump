"""Hot-reload watcher for non-proxy modules.

This module monitors Python source files and reloads them when changes are detected.
Only pure-function modules are reloaded (formatting, rendering, analysis, palette).
Live instances (tui/app.py) and stable boundaries (proxy.py) are never reloaded.

File change detection is handled externally (watchfiles in hot_reload_controller).
This module owns: module classification, reload execution, staleness tracking.
"""

import hashlib
import importlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path

# Modules to reload in dependency order (leaves first, dependents after)
_RELOAD_ORDER = [
    "cc_dump.core.palette",  # no deps within project, base for all colors
    "cc_dump.tui.input_modes",  # no deps within project, pure data
    "cc_dump.tui.category_config",  # no deps within project, pure data
    "cc_dump.tui.panel_registry",  # no deps within project, pure data registry
    "cc_dump.core.analysis",  # no deps within project
    "cc_dump.core.formatting",  # depends on: palette, analysis
    "cc_dump.tui.protocols",  # no deps within project, runtime-checkable protocols
    "cc_dump.tui.action_config",  # depends on: formatting (VisState), pure data
    "cc_dump.app.launch_config",  # depends on: settings (pure data + persistence)
    "cc_dump.app.settings_store",  # depends on: settings (schema + reactions)
    "cc_dump.app.session_store",  # depends on: snarfx only, pure schema
    "cc_dump.app.view_store",  # depends on: formatting (VisState), category_config
    "cc_dump.core.segmentation",  # depends on: nothing (pure parser, before rendering)
    "cc_dump.pipeline.router",  # depends on: nothing within reloadable set
    "cc_dump.tui.search",  # depends on: palette
    "cc_dump.tui.rendering",  # depends on: formatting, palette
    "cc_dump.tui.dump_formatting",  # depends on: formatting
    "cc_dump.tui.chip",  # depends on: nothing (pure widget)
    "cc_dump.tui.location_navigation",  # depends on: nothing (pure navigation helpers)
    "cc_dump.tui.view_overrides",  # depends on: formatting, rendering (lazy import)
    "cc_dump.tui.custom_footer",  # depends on: chip, palette, rendering
    "cc_dump.tui.panel_renderers",  # depends on: analysis
    "cc_dump.app.domain_store",  # depends on: formatting
    "cc_dump.tui.stream_registry",  # depends on: formatting
    "cc_dump.tui.event_handlers",  # depends on: analysis, formatting
    "cc_dump.tui.error_indicator",  # depends on: nothing (pure rendering)
    "cc_dump.tui.info_panel",  # depends on: palette, panel_renderers
    "cc_dump.tui.keys_panel",  # depends on: panel_renderers
    "cc_dump.tui.settings_panel",  # depends on: palette
    "cc_dump.tui.side_channel_panel",  # depends on: palette
    "cc_dump.tui.launch_config_panel",  # depends on: palette, settings_panel
    "cc_dump.tui.session_panel",  # depends on: panel_renderers
    "cc_dump.tui.workbench_results_view",  # depends on: textual widgets only
    "cc_dump.tui.widget_factory",  # depends on: analysis, rendering, panel_renderers, error_indicator
    "cc_dump.tui.dump_export",  # depends on: dump_formatting
    "cc_dump.tui.search_controller",  # depends on: search, location_navigation, category_config
    "cc_dump.tui.theme_controller",  # depends on: rendering
    "cc_dump.tui.action_handlers",  # depends on: formatting, action_config, rendering, widget_factory
    "cc_dump.tui.view_store_bridge",  # depends on: widget_factory, custom_footer, side_channel_panel, action_handlers
]

# Files to explicitly exclude from watching
_EXCLUDED_FILES = {
    "pipeline/proxy.py",  # stable boundary, never reload
    "cli.py",  # entry point, not reloadable at runtime
    "hot_reload.py",  # this file
    "app/tmux_controller.py",  # stable boundary, holds live pane refs
    "ai/side_channel.py",  # stable boundary, holds live subprocess refs
}

# Directories/modules to exclude
_EXCLUDED_MODULES = {
    "tui/app.py",  # live app instance, can't safely reload
    "tui/hot_reload_controller.py",  # accesses live app/widget state
}

# Excluded files worth monitoring for staleness (files a developer would edit).
# [LAW:one-source-of-truth] Staleness is owned solely by this watchlist.
# Keep it small and focused on high-impact boundaries that require restart.
_STALENESS_WATCHLIST = {
    "pipeline/proxy.py",
    "cli.py",
    "app/tmux_controller.py",
    "ai/side_channel.py",
    "tui/app.py",
    "tui/hot_reload_controller.py",
}

_watch_dirs: list[str] = []
_excluded_hashes: dict[str, str] = {}

# Set of reloadable relative paths (derived from _RELOAD_ORDER module names)
_reloadable_rel_paths: set[str] = set()


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

    _scan_excluded_hashes()

    # Build reloadable path set from _RELOAD_ORDER
    # e.g. "cc_dump.core.palette" → "palette.py", "cc_dump.tui.rendering" → "tui/rendering.py"
    _reloadable_rel_paths.clear()
    for mod_name in _RELOAD_ORDER:
        # Strip "cc_dump." prefix, convert dots to slashes, add .py
        rel = mod_name.removeprefix("cc_dump.").replace(".", "/") + ".py"
        _reloadable_rel_paths.add(rel)


def get_watch_paths() -> list[str]:
    """Return directories to watch (set by init())."""
    return list(_watch_dirs)


def is_reloadable(path: str) -> bool:
    """True if path maps to a module in _RELOAD_ORDER.

    Accepts absolute paths or relative paths. For absolute paths,
    resolves against _watch_dirs[0] (the package root).
    """
    if not _watch_dirs:
        return False

    root = Path(_watch_dirs[0])
    p = Path(path)

    # Convert absolute path to relative
    if p.is_absolute():
        try:
            rel = str(p.relative_to(root)).replace(os.sep, "/")
        except ValueError:
            return False
    else:
        rel = str(p).replace(os.sep, "/")

    return rel in _reloadable_rel_paths


def check_and_get_reloaded() -> list[str]:
    """Reload all modules in dependency order.

    Called after external file watcher detects changes.

    Returns:
        List of module names that were reloaded, empty if none.
    """
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


def _iter_excluded_files() -> Iterator[tuple[str, str]]:
    """Yield (abs_path, rel_path) for excluded files worth monitoring for staleness."""
    root = Path(_watch_dirs[0]) if _watch_dirs else None
    seen: set[str] = set()
    for d in _watch_dirs:
        base = Path(d)
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            abs_path = str(path)
            if abs_path in seen:
                continue
            seen.add(abs_path)
            rel_str = str(path.relative_to(root)).replace(os.sep, "/")
            # [LAW:one-source-of-truth] Staleness membership is decided solely by _STALENESS_WATCHLIST.
            if path.name in _STALENESS_WATCHLIST or rel_str in _STALENESS_WATCHLIST:
                yield abs_path, rel_str


def _file_hash(path: str) -> str | None:
    """Return hex SHA-256 of file content, or None on error."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (FileNotFoundError, OSError):
        return None


def _scan_excluded_hashes() -> None:
    """Seed content-hash cache for excluded files."""
    for abs_path, _rel in _iter_excluded_files():
        h = _file_hash(abs_path)
        if h is not None:
            _excluded_hashes[abs_path] = h


def get_stale_excluded() -> list[str]:
    """Return short names of excluded files whose content changed since app start."""
    stale = []
    for abs_path, rel_str in _iter_excluded_files():
        h = _file_hash(abs_path)
        if h is not None and abs_path in _excluded_hashes and _excluded_hashes[abs_path] != h:
            stale.append(rel_str)
    return stale
