# Implementation Context: protocol-definition

## Key Files

### To Create
- `src/cc_dump/tui/protocols.py` - Widget protocol definition
- `HOT_RELOAD_ARCHITECTURE.md` - Architecture documentation
- `tests/test_hot_reload.py` - Import validation test (or add to existing)

### To Modify
- `src/cc_dump/tui/widget_factory.py` - Add return type annotations to factory functions
- `src/cc_dump/hot_reload.py` - Add protocols.py to reload order

### Reference (Read-Only)
- `src/cc_dump/tui/app.py` - Example of stable boundary module
- `src/cc_dump/proxy.py` - Core stable boundary

## Code Patterns

### Protocol Definition Pattern
```python
from typing import Protocol, Dict, Any

class HotSwappableWidget(Protocol):
    def get_state(self) -> Dict[str, Any]: ...
    def restore_state(self, state: Dict[str, Any]) -> None: ...
```

### Factory Return Type Pattern
```python
def create_conversation_view() -> HotSwappableWidget:
    return ConversationView()
```

### Import Validation AST Pattern
```python
import ast

def check_imports(filepath: str, forbidden_modules: set[str]) -> list[str]:
    """Check for 'from module import X' patterns."""
    with open(filepath) as f:
        tree = ast.parse(f.read())

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in forbidden_modules:
                violations.append(f"{filepath}:{node.lineno}: from {node.module} import ...")
    return violations
```

## Module Categories Reference

### Stable Boundary (NEVER reload)
| Module | Reason |
|--------|--------|
| `proxy.py` | HTTP server thread, must stay running |
| `cli.py` | Entry point, already executed |
| `hot_reload.py` | The reloader itself |
| `tui/app.py` | Textual App instance lifecycle |

### Reloadable (Always reload on change)
| Module | Depends On |
|--------|------------|
| `colors.py` | - |
| `analysis.py` | - |
| `formatting.py` | colors, analysis |
| `tui/rendering.py` | formatting, colors |
| `tui/panel_renderers.py` | analysis |
| `tui/event_handlers.py` | analysis, formatting |
| `tui/widget_factory.py` | analysis, rendering, panel_renderers |
| `tui/protocols.py` | - (new) |

### Shim (Re-exports only)
| Module | Re-exports From |
|--------|-----------------|
| `tui/widgets.py` | widget_factory.py |

## Widget State Schema Examples

### ConversationView State
```python
{
    "turn_blocks": list[list[FormattedBlock]],  # Completed turns
    "current_turn_blocks": list[FormattedBlock],  # In-progress turn
    "text_delta_buffer": list[str],  # Buffered streaming text
}
```

### StatsPanel State
```python
{
    "request_count": int,
    "input_tokens": int,
    "output_tokens": int,
    "cache_read_tokens": int,
    "cache_creation_tokens": int,
    "models_seen": set[str],
}
```

### TimelinePanel State
```python
{
    "budgets": list[TurnBudget],
}
```

### ToolEconomicsPanel State
```python
{
    "aggregates": list[ToolAggregates],
}
```
