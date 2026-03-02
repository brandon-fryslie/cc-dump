"""Public formatting API facade.

// [LAW:one-source-of-truth] Canonical implementation lives in formatting_impl;
// this module is the single stable import boundary for callers.
"""

import cc_dump.core.formatting_impl as _impl


# // [LAW:one-source-of-truth] Runtime state stays in formatting_impl.
# // [LAW:dataflow-not-control-flow] Attribute reads delegate through one path.
def __getattr__(name: str):
    return getattr(_impl, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


__all__ = [name for name in dir(_impl) if not name.startswith("__")]
