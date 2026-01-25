# Implementation Context: registry-refactor

## Current State

File: `src/cc_dump/tui/rendering.py` (307 lines)

The `render_block()` function (lines 39-175) is a 137-line if/elif chain:

```python
def render_block(block: FormattedBlock, filters: dict) -> Text | None:
    if isinstance(block, SeparatorBlock):
        if not filters.get("headers", False):
            return None
        char = "\u2500" if block.style == "heavy" else "\u2504"
        return Text(char * 70, style="dim")

    if isinstance(block, HeaderBlock):
        if not filters.get("headers", False):
            return None
        # ... 8 more lines

    # ... 36 more if blocks
```

## Target State

```python
from typing import Callable

# Type alias for render function signature
BlockRenderer = Callable[[FormattedBlock, dict], Text | None]

# Individual render functions
def _render_separator(block: SeparatorBlock, filters: dict) -> Text | None:
    if not filters.get("headers", False):
        return None
    char = "\u2500" if block.style == "heavy" else "\u2504"
    return Text(char * 70, style="dim")

def _render_header(block: HeaderBlock, filters: dict) -> Text | None:
    if not filters.get("headers", False):
        return None
    if block.header_type == "request":
        t = Text()
        t.append(" {} ".format(block.label), style="bold cyan")
        t.append(" ({})".format(block.timestamp), style="dim")
        return t
    else:
        t = Text()
        t.append(" RESPONSE ", style="bold green")
        t.append(" ({})".format(block.timestamp), style="dim")
        return t

# ... (17 more render functions)

# Registry at module level
BLOCK_RENDERERS: dict[type[FormattedBlock], BlockRenderer] = {
    SeparatorBlock: _render_separator,
    HeaderBlock: _render_header,
    MetadataBlock: _render_metadata,
    SystemLabelBlock: _render_system_label,
    TrackedContentBlock: _render_tracked_content,
    DiffBlock: _render_diff,
    RoleBlock: _render_role,
    TextContentBlock: _render_text_content,
    ToolUseBlock: _render_tool_use,
    ToolResultBlock: _render_tool_result,
    ImageBlock: _render_image,
    UnknownTypeBlock: _render_unknown_type,
    StreamInfoBlock: _render_stream_info,
    StreamToolUseBlock: _render_stream_tool_use,
    TextDeltaBlock: _render_text_delta,
    StopReasonBlock: _render_stop_reason,
    ErrorBlock: _render_error,
    ProxyErrorBlock: _render_proxy_error,
    LogBlock: _render_log,
    NewlineBlock: _render_newline,
    TurnBudgetBlock: _render_turn_budget,
}

def render_block(block: FormattedBlock, filters: dict) -> Text | None:
    """Render a FormattedBlock to a Rich Text object."""
    renderer = BLOCK_RENDERERS.get(type(block))
    if renderer is None:
        return None  # Unknown block type - graceful degradation
    return renderer(block, filters)
```

## Refactoring Steps

1. **Extract each if-block into a function**
   - Name: `_render_<lowercase_block_type>` (e.g., `_render_separator`)
   - Signature: `(block: SpecificBlockType, filters: dict) -> Text | None`
   - Move the exact logic from the if-block

2. **Create BLOCK_RENDERERS dict**
   - Key: block class (the type itself, not an instance)
   - Value: render function

3. **Simplify render_block()**
   - Registry lookup
   - None check
   - Call renderer

4. **Handle render_blocks() helper**
   - Keep as-is (it just calls render_block in a loop)

## Block Types Reference

From formatting.py imports at top of rendering.py:

```python
from cc_dump.formatting import (
    FormattedBlock, SeparatorBlock, HeaderBlock, MetadataBlock,
    SystemLabelBlock, TrackedContentBlock, RoleBlock, TextContentBlock,
    ToolUseBlock, ToolResultBlock, ImageBlock, UnknownTypeBlock,
    StreamInfoBlock, StreamToolUseBlock, TextDeltaBlock, StopReasonBlock,
    ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock, TurnBudgetBlock,
    make_diff_lines,
)
```

Note: `DiffBlock` is in formatting.py but may not be imported. Check if used.

## Filter Key Mapping

| Block Type | Filter Key | Filter Behavior |
|------------|------------|-----------------|
| SeparatorBlock | headers | Hide if headers=False |
| HeaderBlock | headers | Hide if headers=False |
| MetadataBlock | metadata | Hide if metadata=False |
| SystemLabelBlock | system | Hide if system=False |
| TrackedContentBlock | system + expand | Complex logic based on status |
| RoleBlock | (none) | Always show |
| TextContentBlock | (none) | Always show |
| ToolUseBlock | tools | Hide if tools=False |
| ToolResultBlock | tools | Hide if tools=False |
| StreamInfoBlock | metadata | Hide if metadata=False |
| StreamToolUseBlock | tools | Hide if tools=False |
| TurnBudgetBlock | expand | Hide if expand=False |
| ErrorBlock | (none) | Always show |
| ProxyErrorBlock | (none) | Always show |
| NewlineBlock | (none) | Always show |
| TextDeltaBlock | (none) | Always show |
| StopReasonBlock | metadata | Hide if metadata=False |

## Testing Strategy

Create `tests/test_rendering.py`:

```python
"""Unit tests for tui/rendering.py registry pattern."""

import pytest
from rich.text import Text
from cc_dump.formatting import (
    SeparatorBlock, HeaderBlock, MetadataBlock, TextContentBlock,
)
from cc_dump.tui.rendering import (
    render_block, BLOCK_RENDERERS,
    _render_separator, _render_header,
)

class TestBlockRegistry:
    def test_registry_contains_all_block_types(self):
        # Check registry has entries for all known block types
        assert SeparatorBlock in BLOCK_RENDERERS
        assert HeaderBlock in BLOCK_RENDERERS
        # ... etc

    def test_registry_lookup_unknown_type(self):
        class UnknownBlock:
            pass
        assert render_block(UnknownBlock(), {}) is None

class TestIndividualRenderers:
    def test_render_separator_with_headers_filter(self):
        block = SeparatorBlock(style="heavy")
        result = _render_separator(block, {"headers": True})
        assert isinstance(result, Text)
        assert "─" in str(result)

    def test_render_separator_without_headers_filter(self):
        block = SeparatorBlock(style="heavy")
        result = _render_separator(block, {"headers": False})
        assert result is None
```

## Hot-Reload Compatibility

The registry pattern is hot-reload compatible because:
1. `BLOCK_RENDERERS` is a module-level dict
2. After `importlib.reload(cc_dump.tui.rendering)`, the new dict is used
3. All render functions are module-level (not instance methods)

No changes needed to hot_reload.py.
