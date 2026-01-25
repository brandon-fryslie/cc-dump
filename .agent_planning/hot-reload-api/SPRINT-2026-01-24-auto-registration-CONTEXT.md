# Implementation Context: auto-registration

## Key Files

### To Modify
- `src/cc_dump/hot_reload.py` - Replace hardcoded list with discovery

### Reference
- `src/cc_dump/tui/widget_factory.py` - Example of module with imports to track

## Code Patterns

### Module Discovery Pattern
```python
import os
from pathlib import Path

_STABLE_BOUNDARY = {
    "cc_dump.proxy",
    "cc_dump.cli",
    "cc_dump.hot_reload",
    "cc_dump.tui.app",
}

def _discover_modules(package_dir: str) -> set[str]:
    """Discover all reloadable modules in the package."""
    modules = set()

    for root, dirs, files in os.walk(package_dir):
        # Skip __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]

        for fname in files:
            if not fname.endswith(".py"):
                continue
            if fname.startswith("__"):
                continue

            path = Path(root) / fname
            rel = path.relative_to(Path(package_dir).parent)
            mod_name = str(rel).replace("/", ".").replace("\\", ".")[:-3]

            if mod_name not in _STABLE_BOUNDARY:
                modules.add(mod_name)

    return modules
```

### Dependency Graph Building
```python
import ast
from collections import defaultdict

def _extract_imports(filepath: str) -> set[str]:
    """Extract cc_dump imports from a Python file."""
    with open(filepath) as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("cc_dump."):
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("cc_dump."):
                imports.add(node.module)

    return imports

def _build_dependency_graph(modules: set[str], package_dir: str) -> dict[str, set[str]]:
    """Build dependency graph: module -> modules it depends on."""
    graph = defaultdict(set)

    for mod in modules:
        path = _module_to_path(mod, package_dir)
        if path and os.path.exists(path):
            deps = _extract_imports(path)
            # Only track internal deps
            graph[mod] = deps & modules

    return graph
```

### Topological Sort Pattern
```python
def _topological_sort(graph: dict[str, set[str]]) -> list[str]:
    """Sort modules so dependencies come before dependents."""
    # Kahn's algorithm
    in_degree = {node: 0 for node in graph}
    for deps in graph.values():
        for dep in deps:
            if dep in in_degree:
                in_degree[dep] += 1

    # Start with nodes that have no dependencies
    queue = [node for node, degree in in_degree.items() if degree == 0]
    result = []

    while queue:
        node = queue.pop(0)
        result.append(node)

        for dependent, deps in graph.items():
            if node in deps:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

    if len(result) != len(graph):
        # Circular dependency - fall back to alphabetical
        missing = set(graph.keys()) - set(result)
        result.extend(sorted(missing))

    return result
```

## Current _RELOAD_ORDER for Reference
```python
_RELOAD_ORDER = [
    "cc_dump.colors",
    "cc_dump.analysis",
    "cc_dump.formatting",
    "cc_dump.tui.rendering",
    "cc_dump.tui.panel_renderers",
    "cc_dump.tui.event_handlers",
    "cc_dump.tui.widget_factory",
]
```

Expected computed order should match this (with colors/analysis first since they have no deps).

## Testing Strategy

1. **Unit test**: Verify discovery finds all expected modules
2. **Unit test**: Verify dependency graph is correct
3. **Unit test**: Verify topological sort handles cycles
4. **Integration test**: Full reload cycle with auto-registration
