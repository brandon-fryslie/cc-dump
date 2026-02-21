"""Guard: no function-level `import cc_dump` inside src/.

A function-level `import cc_dump.x.y` shadows the module-level `cc_dump`
binding for the ENTIRE enclosing function, causing UnboundLocalError on
any `cc_dump.` reference that precedes the import statement.

This file is named with `test_0_` so it runs first.
"""

import ast
import os


_SRC_ROOT = os.path.join(os.path.dirname(__file__), "..", "src", "cc_dump")

# Intentional hot-reload imports in reloadable modules where the function
# has no other cc_dump.* references before the import.  (file, lineno) tuples.
_ALLOWLIST = {
    (os.path.join("tui", "view_overrides.py"), 70),
    (os.path.join("tui", "launch_config_panel.py"), 376),
}


def _find_function_level_cc_dump_imports():
    """Walk all .py files and flag `import cc_dump.*` inside functions/methods."""
    violations = []
    for dirpath, _dirs, files in os.walk(_SRC_ROOT):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(dirpath, fname)
            with open(path) as f:
                try:
                    tree = ast.parse(f.read(), filename=path)
                except SyntaxError:
                    continue

            rel = os.path.relpath(path, _SRC_ROOT)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for child in ast.walk(node):
                    if isinstance(child, ast.Import):
                        for alias in child.names:
                            if alias.name.startswith("cc_dump"):
                                if (rel, child.lineno) in _ALLOWLIST:
                                    continue
                                violations.append(
                                    f"{rel}:{child.lineno} "
                                    f"function-level `import {alias.name}`"
                                )
    return violations


def test_no_function_level_cc_dump_imports():
    violations = _find_function_level_cc_dump_imports()
    assert violations == [], (
        "Function-level `import cc_dump.*` shadows the module binding and "
        "causes UnboundLocalError. Move these to module level:\n"
        + "\n".join(f"  {v}" for v in violations)
    )
