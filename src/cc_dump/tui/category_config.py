"""Category visibility configuration.

// [LAW:one-source-of-truth] Single definition of category keys, names, and defaults.
// [LAW:one-type-per-behavior] All categories are instances of one tuple shape.

This module is pure data — safe for `from` imports. Not hot-reloadable
(loaded once at import time; changes require restart).
"""

import cc_dump.core.formatting

# (key, category_name, description, default_visstate)
# // [LAW:one-source-of-truth] 6 categories: METADATA consolidates former budget/metadata/headers.
CATEGORY_CONFIG = [
    ("1", "user", "user", cc_dump.core.formatting.VisState(True, True, True)),
    ("2", "assistant", "assistant", cc_dump.core.formatting.VisState(True, True, True)),
    ("3", "tools", "tools", cc_dump.core.formatting.VisState(True, False, False)),
    ("4", "system", "system", cc_dump.core.formatting.VisState(True, False, False)),
    ("5", "metadata", "metadata", cc_dump.core.formatting.VisState(False, False, False)),
    ("6", "thinking", "thinking", cc_dump.core.formatting.VisState(True, False, False)),
]
