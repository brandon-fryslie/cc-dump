# Implementation Context: formatting-ir
Generated: 2026-01-24

## Files to Create
- `src/cc_dump/formatting_ansi.py`

## Files to Modify
- `src/cc_dump/display.py` — rewrite to use block→ANSI chain
- `src/cc_dump/cli.py` — add `formatting_ansi` to hot-reload list

## Key Implementation Details

### formatting_ansi.py structure

```python
from cc_dump.colors import (BOLD, CYAN, DIM, GREEN, MAGENTA, RED, RESET,
                             SEPARATOR, TAG_COLORS, THIN_SEP, WHITE, YELLOW)
from cc_dump.formatting import (
    FormattedBlock, SeparatorBlock, HeaderBlock, MetadataBlock,
    SystemLabelBlock, TrackedContentBlock, RoleBlock, TextContentBlock,
    ToolUseBlock, ToolResultBlock, ImageBlock, UnknownTypeBlock,
    StreamInfoBlock, StreamToolUseBlock, TextDeltaBlock, StopReasonBlock,
    ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock, make_diff_lines,
)

MSG_COLORS = [CYAN, GREEN, YELLOW, MAGENTA, BLUE, RED]  # 6-color cycle

def render_block(block: FormattedBlock) -> str:
    """Render a single block to ANSI string."""
    # isinstance dispatch for each block type
    ...

def render_blocks(blocks: list[FormattedBlock]) -> str:
    """Render a list of blocks, joining with newlines (except TextDeltaBlock)."""
    ...
```

### display.py changes
- Import `render_blocks`, `render_block` from `formatting_ansi`
- `"request"` handler: `blocks = format_request(body, state)` then `render_blocks(blocks)` → stdout
- `"response_event"` handler: `blocks = format_response_event(event_type, data)` then render each
- `"response_start"` / `"error"` / etc: can stay as direct string writes (they're simple)

### Color mapping for roles
```python
def _role_str(role):
    icons = {
        "user": CYAN + BOLD + "USER" + RESET,
        "assistant": GREEN + BOLD + "ASSISTANT" + RESET,
        "system": YELLOW + BOLD + "SYSTEM" + RESET,
    }
    return icons.get(role, MAGENTA + BOLD + role.upper() + RESET)
```

### TrackedContentBlock rendering
- "new": `{indent}  {tag} NEW ({len} chars):\n{indented content}`
- "ref": `{indent}  {tag} (unchanged)`
- "changed": `{indent}  {tag} CHANGED ({old_len} -> {new_len} chars):\n{diff}`

### Tag rendering
```python
def _format_tag(tag_id, color_idx):
    fg, bg = TAG_COLORS[color_idx % len(TAG_COLORS)]
    return bg + fg + BOLD + " {} ".format(tag_id) + RESET
```
