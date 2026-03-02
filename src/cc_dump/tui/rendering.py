"""Public rendering API facade.

// [LAW:one-source-of-truth] Canonical implementation lives in rendering_impl;
// this module remains the stable import boundary for app/tests/hot-reload.
"""

import cc_dump.tui.rendering_impl as _impl


# Keep a local mirror for tests that intentionally mutate module globals.
# // [LAW:one-source-of-truth] Source of truth is still rendering_impl.
_theme_colors = _impl._theme_colors


def set_theme(textual_theme) -> None:
    """Delegate theme rebuild and mirror mutable theme state for test compatibility."""
    global _theme_colors
    _impl.set_theme(textual_theme)
    _theme_colors = _impl._theme_colors


def get_theme_colors():
    """Read theme state after syncing local test-overrides into rendering_impl."""
    _impl._theme_colors = _theme_colors
    return _impl.get_theme_colors()


# // [LAW:one-source-of-truth] Runtime state stays in rendering_impl.
# // [LAW:dataflow-not-control-flow] Attribute reads delegate through one path.
def __getattr__(name: str):
    return getattr(_impl, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


__all__ = [name for name in dir(_impl) if not name.startswith("__")]
