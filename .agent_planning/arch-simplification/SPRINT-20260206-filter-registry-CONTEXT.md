# Implementation Context: filter-registry

## Current Duplication Sites (exact locations)

### 1. palette.py:66-75
```python
_FILTER_INDICATOR_INDEX = {
    "headers": 0, "tools": 1, "system": 2,
    "expand": 3, "metadata": 4,  # ← "expand" becomes "budget" after Sprint 1
    "stats": 5, "economics": 6, "timeline": 7,
}
```

### 2. app.py — reactive properties (class level)
```python
show_headers = reactive(False)
show_tools = reactive(False)
show_system = reactive(False)
show_expand = reactive(False)  # ← becomes show_budget
show_metadata = reactive(False)
show_stats = reactive(False)
show_economics = reactive(False)
show_timeline = reactive(False)
```

### 3. app.py — active_filters property
```python
@property
def active_filters(self) -> dict:
    return {
        "headers": self.show_headers,
        "tools": self.show_tools,
        # ... 8 entries
    }
```

### 4. custom_footer.py:72-81
```python
ACTION_TO_FILTER = {
    "toggle_headers": "headers",
    "toggle_tools": "tools",
    # ... 8 entries
}
```

### 5. rendering.py — BLOCK_FILTER_KEY
```python
BLOCK_FILTER_KEY = {
    "HeaderBlock": "headers",
    "ToolUseBlock": "tools",
    # ... maps block type names to filter keys
}
```

### 6. widget_factory.py — FilterStatusBar (partial)
Hardcodes content filter names for display.

## Two Filter Types
- **Content filters** (headers, tools, system, budget, metadata): control block visibility in rendering.py
- **Panel filters** (stats, economics, timeline): control widget visibility in app.py

These have different semantics but share the same reactive property + dict pattern. A registry should distinguish them with a `filter_type` field.

## Registry Shape (proposed)

```python
FILTERS = [
    FilterDef(key="headers", label="Headers", type="content", default=False, color_idx=0, keybinding="h", block_types=["HeaderBlock", "SeparatorBlock", "HttpHeadersBlock"]),
    FilterDef(key="tools", label="Tools", type="content", default=False, color_idx=1, block_types=["ToolUseBlock", "ToolResultBlock", "ToolUseSummaryBlock"]),
    # ...
]
```

Each consumer derives its data structure from this list.
