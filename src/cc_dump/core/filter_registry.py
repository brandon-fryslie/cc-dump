"""Canonical filter/category registry shared across TUI consumers.

// [LAW:one-source-of-truth] Filter keys, names, defaults, and indicator slots live here.
// [LAW:one-type-per-behavior] Every filter category is one FilterSpec instance.
"""

from __future__ import annotations

from typing import NamedTuple

from cc_dump.core.formatting import VisState


class FilterSpec(NamedTuple):
    key: str
    name: str
    description: str
    default: VisState
    indicator_index: int


# // [LAW:one-source-of-truth] Single registry for all category/filter metadata.
FILTER_SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("1", "user", "user", VisState(True, True, True), 3),
    FilterSpec("2", "assistant", "assistant", VisState(True, True, True), 4),
    FilterSpec("3", "tools", "tools", VisState(True, False, False), 0),
    FilterSpec("4", "system", "system", VisState(True, False, False), 1),
    FilterSpec("5", "metadata", "metadata", VisState(False, False, False), 2),
    FilterSpec("6", "thinking", "thinking", VisState(True, False, False), 5),
)


# Back-compat shape used by existing callers/tests.
CATEGORY_CONFIG: list[tuple[str, str, str, VisState]] = [
    (spec.key, spec.name, spec.description, spec.default) for spec in FILTER_SPECS
]

# Footer row order is key order.
CATEGORY_ITEMS: tuple[tuple[str, str], ...] = tuple(
    (spec.key, spec.name) for spec in FILTER_SPECS
)

# Palette indicator layout is indicator-index order.
_INDICATOR_ORDERED: tuple[FilterSpec, ...] = tuple(
    sorted(FILTER_SPECS, key=lambda spec: spec.indicator_index)
)
FILTER_INDICATOR_INDEX: dict[str, int] = {
    spec.name: spec.indicator_index for spec in _INDICATOR_ORDERED
}
FILTER_INDICATOR_NAMES: tuple[str, ...] = tuple(spec.name for spec in _INDICATOR_ORDERED)
