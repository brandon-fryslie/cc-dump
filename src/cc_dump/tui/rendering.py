"""Public rendering API facade.

// [LAW:one-source-of-truth] Canonical implementation lives in rendering_impl;
// this module remains the stable import boundary for app/tests/hot-reload.
"""

import cc_dump.tui.rendering_impl as _impl


# // [LAW:one-source-of-truth] Runtime state stays in rendering_impl.
# // [LAW:dataflow-not-control-flow] Attribute reads delegate through one path.
def __getattr__(name: str):
    return getattr(_impl, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


__all__ = [name for name in dir(_impl) if not name.startswith("__")]
