"""Category visibility configuration.

// [LAW:one-source-of-truth] Single definition of category keys, names, and defaults.
// [LAW:one-type-per-behavior] All categories are instances of one tuple shape.

This module is pure data — safe for `from` imports. Not hot-reloadable
(loaded once at import time; changes require restart).
"""

import cc_dump.formatting

# (key, category_name, description, default_visstate)
CATEGORY_CONFIG = [
    ("1", "headers", "headers", cc_dump.formatting.VisState(False, False, False)),
    ("2", "user", "user", cc_dump.formatting.VisState(True, True, True)),
    ("3", "assistant", "assistant", cc_dump.formatting.VisState(True, True, True)),
    ("4", "tools", "tools", cc_dump.formatting.VisState(True, False, False)),
    ("5", "system", "system", cc_dump.formatting.VisState(True, False, False)),
    ("6", "budget", "budget", cc_dump.formatting.VisState(False, False, False)),
    ("7", "metadata", "metadata", cc_dump.formatting.VisState(False, False, False)),
]
