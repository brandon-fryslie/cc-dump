"""Hot-reload watcher for non-proxy modules.

This module monitors Python source files and reloads them when changes are detected.
Only pure-function modules are reloaded (formatting, rendering, analysis, palette).
Live instances (tui/app.py) and stable boundaries (proxy.py) are never reloaded.

File change detection is handled externally (watchfiles in hot_reload_controller).
This module owns: module classification, reload execution, staleness tracking.
"""

import hashlib
import importlib
import logging
import os
import sys
from types import ModuleType
from collections.abc import Iterator
from pathlib import Path

# Modules to reload in dependency order (leaves first, dependents after)
_RELOAD_ORDER = [
    "cc_dump.core.palette",  # no deps within project, base for all colors
    "cc_dump.tui.input_modes",  # no deps within project, pure data
    "cc_dump.core.analysis",  # no deps within project
    "cc_dump.core.formatting_impl",  # depends on: palette, analysis
    "cc_dump.core.formatting",  # facade depends on: formatting_impl
    "cc_dump.core.coerce",  # shared pure coercion helpers
    "cc_dump.tui.action_config",  # depends on: formatting (VisState), pure data
    "cc_dump.app.launch_config",  # depends on: settings (pure data + persistence)
    "cc_dump.app.error_models",  # shared pure error view-models
    "cc_dump.app.settings_store",  # depends on: settings (schema + reactions)
    "cc_dump.app.view_store",  # depends on: formatting (VisState), category_config
    "cc_dump.core.segmentation",  # depends on: nothing (pure parser, before rendering)
    "cc_dump.pipeline.router",  # depends on: nothing within reloadable set
    "cc_dump.tui.search",  # depends on: palette
    "cc_dump.tui.rendering_impl",  # depends on: formatting, palette
    "cc_dump.tui.rendering",  # facade depends on: rendering_impl
    "cc_dump.tui.dump_formatting",  # depends on: formatting
    "cc_dump.tui.chip",  # depends on: nothing (pure widget)
    "cc_dump.tui.cycle_selector",  # depends on: nothing (pure widget)
    "cc_dump.tui.store_widget",  # depends on: nothing (pure mixin)
    "cc_dump.tui.custom_footer",  # depends on: chip, palette, rendering, store_widget, widget_factory
    "cc_dump.tui.panel_renderers",  # depends on: analysis
    "cc_dump.app.domain_store",  # depends on: formatting
    "cc_dump.tui.stream_registry",  # depends on: formatting
    "cc_dump.tui.event_handlers",  # depends on: analysis, formatting
    "cc_dump.tui.error_indicator",  # depends on: nothing (pure rendering)
    "cc_dump.tui.info_panel",  # depends on: palette, panel_renderers
    "cc_dump.tui.keys_panel",  # depends on: panel_renderers
    "cc_dump.tui.settings_panel",  # depends on: palette
    "cc_dump.tui.debug_settings_panel",  # depends on: palette, chip, perf_logging
    "cc_dump.tui.side_channel_panel",  # depends on: palette
    "cc_dump.tui.side_channel_controller",  # depends on: side_channel_panel
    "cc_dump.tui.launch_config_panel",  # depends on: palette, settings_panel
    "cc_dump.tui.settings_launch_controller",  # depends on: launch_config_panel, settings_panel
    "cc_dump.tui.session_panel",  # depends on: panel_renderers
    "cc_dump.tui.widget_factory",  # depends on: analysis, rendering, panel_renderers, error_indicator
    "cc_dump.tui.dump_export",  # depends on: dump_formatting
    "cc_dump.tui.theme_controller",  # depends on: rendering
    "cc_dump.tui.action_handlers",  # depends on: formatting, action_config, rendering, widget_factory
    "cc_dump.tui.view_store_bridge",  # depends on: widget_factory, custom_footer, side_channel_panel, action_handlers
    "cc_dump.tui.lifecycle_controller",  # depends on: rendering, view_store_bridge
]

# Files to explicitly exclude from watching
_EXCLUDED_FILES = {
    "pipeline/proxy.py",  # stable boundary, never reload
    "pipeline/forward_proxy_tls.py",  # stable boundary, holds crypto state
    "cli.py",  # entry point, not reloadable at runtime
    "hot_reload.py",  # this file
    "pipeline/event_types.py",  # stable type definitions, never reload
    "pipeline/response_assembler.py",  # stable boundary, imported by proxy.py
    "app/tmux_controller.py",  # stable boundary, holds live pane refs
    "io/stderr_tee.py",  # stable boundary, holds live sys.stderr ref
    "ai/side_channel.py",  # stable boundary, holds live subprocess refs
    "ai/data_dispatcher.py",  # stable boundary, holds ref to side_channel
    "__init__.py",  # module init
    "__main__.py",  # entry point
}

# Directories/modules to exclude
_EXCLUDED_MODULES = {
    "tui/app.py",  # live app instance, can't safely reload
    "tui/category_config.py",  # pure data, but referenced at init time
    "tui/search_controller.py",  # accesses live app/widget state
    "tui/hot_reload_controller.py",  # accesses live app/widget state
    "tui/panel_registry.py",  # stable pure data, referenced at init time
}

# Excluded files worth monitoring for staleness (files a developer would edit).
# Subset of _EXCLUDED_FILES ∪ _EXCLUDED_MODULES, minus boilerplate nobody touches.
_STALENESS_WATCHLIST = {
    # from _EXCLUDED_FILES
    "pipeline/proxy.py", "pipeline/forward_proxy_tls.py", "cli.py", "pipeline/event_types.py", "pipeline/response_assembler.py",
    "app/tmux_controller.py", "io/stderr_tee.py", "ai/side_channel.py", "ai/data_dispatcher.py",
    # from _EXCLUDED_MODULES
    "tui/app.py", "tui/category_config.py",
    "tui/search_controller.py",
    "tui/hot_reload_controller.py",
}

_watch_dirs: list[str] = []
_excluded_hashes: dict[str, str] = {}

# Set of reloadable relative paths (derived from _RELOAD_ORDER module names)
_reloadable_rel_paths: set[str] = set()
logger = logging.getLogger(__name__)


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
    old_exports = _snapshot_reloaded_exports(to_reload)

    # Reload in order
    reloaded = []
    for mod_name in to_reload:
        mod = sys.modules.get(mod_name)
        if mod:
            try:
                importlib.reload(mod)
                reloaded.append(mod_name)
            except Exception:
                logger.exception("hot-reload error while reloading module %s", mod_name)
                # Continue with other modules even if one fails
                # This way a syntax error in one module doesn't break the whole reload

    _refresh_top_level_import_aliases(old_exports, reloaded)

    if reloaded:
        logger.info(
            "hot-reload reloaded %d module(s): %s",
            len(reloaded),
            ", ".join(reloaded),
        )

    return reloaded


def _snapshot_reloaded_exports(module_names: list[str]) -> dict[str, dict[str, object]]:
    """Capture pre-reload exported names for modules we intend to reload.

    // [LAW:one-source-of-truth] Old->new alias refresh is derived from this snapshot.
    """
    snapshot: dict[str, dict[str, object]] = {}
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        values = {
            name: value
            for name, value in vars(module).items()
            if not name.startswith("__") and _is_alias_refreshable_export(module_name, value)
        }
        snapshot[module_name] = values
    return snapshot


def _is_alias_refreshable_export(module_name: str, value: object) -> bool:
    """True when an export is safe and meaningful for alias refresh mapping.

    Restricting to module-owned symbols prevents accidental global rebinding caused
    by shared primitive identities from interning/caching (for example int/str/None).
    """
    if isinstance(value, str | bytes | int | float | complex | bool | tuple | frozenset | list | dict | set | type(None)):
        return False

    value_module = getattr(value, "__module__", None)
    if value_module == module_name:
        return True

    value_type_module = getattr(type(value), "__module__", None)
    return value_type_module == module_name


def _refresh_top_level_import_aliases(
    old_exports: dict[str, dict[str, object]],
    reloaded_modules: list[str],
) -> None:
    """Refresh stale `from x import y` aliases across already-loaded cc_dump modules.

    // [LAW:single-enforcer] Alias rebinding happens in one centralized pass after reload.
    """
    replacements = _build_alias_replacements(old_exports, reloaded_modules)
    if not replacements:
        return

    updated_bindings = _apply_alias_replacements(replacements)
    if updated_bindings:
        logger.info("hot-reload refreshed %d top-level import alias(es)", updated_bindings)


def _build_alias_replacements(
    old_exports: dict[str, dict[str, object]],
    reloaded_modules: list[str],
) -> dict[int, object]:
    replacements: dict[int, object] = {}
    for module_name in reloaded_modules:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        old_values = old_exports.get(module_name, {})
        for name, old_value in old_values.items():
            new_value = getattr(module, name, old_value)
            if new_value is not old_value:
                replacements[id(old_value)] = new_value
    return replacements


def _iter_cc_dump_module_dicts() -> Iterator[dict[str, object]]:
    for module in list(sys.modules.values()):
        if not isinstance(module, ModuleType):
            continue
        module_name = getattr(module, "__name__", "")
        if not module_name.startswith("cc_dump."):
            continue
        module_dict = getattr(module, "__dict__", None)
        if isinstance(module_dict, dict):
            yield module_dict


def _apply_alias_replacements(replacements: dict[int, object]) -> int:
    updated_bindings = 0
    for module_dict in _iter_cc_dump_module_dicts():
        for name, value in list(module_dict.items()):
            value_id = id(value)
            if value_id in replacements:
                module_dict[name] = replacements[value_id]
                updated_bindings += 1
    return updated_bindings


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
