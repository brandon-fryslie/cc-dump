"""Category visibility configuration.

// [LAW:one-source-of-truth] Canonical definitions live in core.filter_registry.
// [LAW:one-type-per-behavior] All categories are instances of one tuple shape.

This module is pure data and hot-reloadable.
"""

from cc_dump.core.filter_registry import CATEGORY_CONFIG

__all__ = ["CATEGORY_CONFIG"]
