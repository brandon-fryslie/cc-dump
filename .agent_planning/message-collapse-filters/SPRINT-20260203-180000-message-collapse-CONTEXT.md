# Implementation Context: message-collapse
Generated: 2026-02-03T18:00:00
Source: EVALUATION-20260203-180000.md
Confidence: HIGH

## File-by-File Changes

---

### 1. `src/cc_dump/tui/app.py`

**Add reactive state** (after line 56):
```python
show_user_messages = reactive(False)
show_assistant_messages = reactive(False)
```

**Add bindings** (in BINDINGS list, around line 35):
```python
Binding("u", "toggle_user_messages", "u|ser msg", show=True),
Binding("d", "toggle_assistant_messages", "|d|etail asst", show=True),
```

**Add to active_filters property** (line 483-495):
```python
@property
def active_filters(self):
    return {
        "headers": self.show_headers,
        "tools": self.show_tools,
        "system": self.show_system,
        "expand": self.show_expand,
        "metadata": self.show_metadata,
        "stats": self.show_stats,
        "economics": self.show_economics,
        "timeline": self.show_timeline,
        "user": self.show_user_messages,        # NEW
        "assistant": self.show_assistant_messages,  # NEW
    }
```

**Add action handlers** (after line 509, following pattern of `action_toggle_expand`):
```python
def action_toggle_user_messages(self):
    self.show_user_messages = not self.show_user_messages

def action_toggle_assistant_messages(self):
    self.show_assistant_messages = not self.show_assistant_messages
```

**Add watchers** (after line 624):
```python
def watch_show_user_messages(self, value):
    self._rerender_if_mounted()

def watch_show_assistant_messages(self, value):
    self._rerender_if_mounted()
```

---

### 2. `src/cc_dump/tui/rendering.py`

**Add filter indicators** (in `_build_filter_indicators()`, line 42-50):
Add entries for "user" and "assistant":
```python
"user": ("\u25cc", p.filter_color("user")),       # dotted circle or use existing indicator
"assistant": ("\u25cc", p.filter_color("assistant")),
```

**Add new collapse renderer** (new function, after `_render_text_content` at line 198):
```python
def _render_text_content_collapsed(block: TextContentBlock, filters: dict, role_filter_key: str) -> Text | None:
    """Render text content with collapse behavior for role-based filters.

    When the role filter is off (collapsed), shows first 2 lines with arrow indicator.
    When on (expanded), shows full content with down arrow if >2 lines.
    Messages with <=2 lines are always shown in full without arrow.
    """
    if not block.text:
        return None

    lines = block.text.splitlines()
    is_expanded = filters.get(role_filter_key, False)

    if len(lines) <= 2:
        # Short message: always show full, no arrow
        return _indent_text(block.text, block.indent)

    if is_expanded:
        # Expanded: full content with down arrow
        t = Text()
        t.append("\u25bc ", style="dim")  # down arrow
        t.append(_indent_text(block.text, block.indent))
        return _add_filter_indicator(t, role_filter_key)
    else:
        # Collapsed: first 2 lines with right arrow
        truncated = "\n".join(lines[:2])
        t = Text()
        t.append("\u25b6 ", style="dim")  # right arrow
        t.append(_indent_text(truncated, block.indent))
        remaining = len(lines) - 2
        t.append(f"\n{block.indent}  ... ({remaining} more lines)", style="dim")
        return _add_filter_indicator(t, role_filter_key)
```

**Modify render_blocks()** (line 380-424):
Add role tracking. The key change is in the `for i, block in enumerate(blocks)` loop.

Current code at line 410:
```python
for i, block in enumerate(blocks):
    is_tool_use = type(block).__name__ == "ToolUseBlock"
    if is_tool_use and not tools_on:
        pending_tool_uses.append((i, block))
        continue
    flush_tool_uses()
    block_expanded = expanded_overrides.get(i) if expanded_overrides else None
    r = render_block(block, filters, expanded=block_expanded)
    if r is not None:
        rendered.append((i, r))
```

Modified to:
```python
current_role = None  # Track role for message collapse

for i, block in enumerate(blocks):
    block_name = type(block).__name__

    # Track current role from RoleBlock
    if block_name == "RoleBlock":
        current_role = block.role.lower()

    is_tool_use = block_name == "ToolUseBlock"
    if is_tool_use and not tools_on:
        pending_tool_uses.append((i, block))
        continue
    flush_tool_uses()

    # Role-based collapse for TextContentBlock
    if block_name == "TextContentBlock" and current_role in ("user", "assistant"):
        role_filter_key = current_role  # "user" or "assistant"
        r = _render_text_content_collapsed(block, filters, role_filter_key)
        if r is not None:
            rendered.append((i, r))
        continue

    block_expanded = expanded_overrides.get(i) if expanded_overrides else None
    r = render_block(block, filters, expanded=block_expanded)
    if r is not None:
        rendered.append((i, r))
```

Note: `tool_result` role should NOT trigger collapse (those are tool outputs, not user text).

---

### 3. `src/cc_dump/tui/widget_factory.py`

**Modify TurnData.compute_relevant_keys()** (line 62-73):
Add role-based filter key detection.

Current:
```python
def compute_relevant_keys(self):
    keys = set()
    for block in self.blocks:
        key = cc_dump.tui.rendering.get_block_filter_key(type(block).__name__)
        if key is not None:
            keys.add(key)
    self.relevant_filter_keys = keys
```

Modified:
```python
def compute_relevant_keys(self):
    keys = set()
    current_role = None
    for block in self.blocks:
        block_name = type(block).__name__
        key = cc_dump.tui.rendering.get_block_filter_key(block_name)
        if key is not None:
            keys.add(key)
        # Track role for message-collapse filter relevance
        if block_name == "RoleBlock":
            current_role = block.role.lower()
        elif block_name == "TextContentBlock" and current_role in ("user", "assistant"):
            keys.add(current_role)  # "user" or "assistant"
    self.relevant_filter_keys = keys
```

---

### 4. `src/cc_dump/palette.py`

**Add filter index entries** (line 66-74, in `_FILTER_INDICATOR_INDEX` dict):
```python
_FILTER_INDICATOR_INDEX: dict[str, int] = {
    "headers":    0,  # strawberry-red
    "tools":      1,  # atomic-tangerine
    "system":     2,  # carrot-orange
    "expand":     3,  # tuscan-sun
    "metadata":   4,  # golden-sand
    "stats":      5,  # willow-green
    "economics":  6,  # mint-leaf
    "timeline":   7,  # seagrass
    "user":       8,  # dark-cyan       # NEW
    "assistant":  9,  # blue-slate      # NEW
}
```

The 10-color `_INDICATOR_COLORS` list already has entries at indices 8 and 9:
- Index 8: dark-cyan `#4D908E`
- Index 9: blue-slate `#577590`

`filter_color()` and `filter_bg()` will automatically pick these up via the index lookup.

---

### 5. `src/cc_dump/tui/custom_footer.py`

**Add to _init_palette_colors()** (line 72-81):
Add entries to `_filter_names` list:
```python
("toggle_user_messages", "user"),
("toggle_assistant_messages", "assistant"),
```

---

### 6. `tests/test_widget_arch.py`

**New test class** (at end of file):
```python
class TestMessageCollapseFilters:
    """Test user and assistant message collapse/expand behavior."""

    def test_user_message_collapsed_when_filter_off(self):
        # Create blocks: RoleBlock(user) + TextContentBlock(5 lines)
        # Call render_blocks with filters={"user": False}
        # Assert rendered text has only 2 content lines + "... (3 more lines)"

    def test_user_message_expanded_when_filter_on(self):
        # filters={"user": True}
        # Assert all 5 lines present

    def test_no_arrow_for_short_messages(self):
        # TextContentBlock with 2 lines
        # filters={"user": False}
        # Assert no arrow, full content shown

    def test_assistant_message_collapse_independent(self):
        # filters={"user": True, "assistant": False}
        # User text expanded, assistant text collapsed

    def test_compute_relevant_keys_includes_role_filters(self):
        # TurnData with user RoleBlock + TextContentBlock
        # Assert "user" in relevant_filter_keys

    def test_system_messages_unaffected(self):
        # RoleBlock(system) + TextContentBlock
        # Not affected by user/assistant filters

    def test_tool_result_messages_unaffected(self):
        # RoleBlock(tool_result) + TextContentBlock
        # Not affected by user/assistant filters
```

---

## Adjacent Code Patterns to Follow

### Filter toggle pattern (app.py):
```python
# Existing pattern at line 48-56:
show_headers = reactive(False)
# ...
def action_toggle_headers(self):
    self.show_headers = not self.show_headers
# ...
def watch_show_headers(self, value):
    self._rerender_if_mounted()
```

### Tool collapse pattern (rendering.py lines 400-424):
```python
# render_blocks() already tracks state across blocks for tool collapse:
pending_tool_uses: list[tuple[int, ToolUseBlock]] = []
def flush_tool_uses():
    if pending_tool_uses:
        # ...create summary...
        pending_tool_uses.clear()
```

### Collapse/expand arrow pattern (rendering.py lines 516-558):
```python
# TrackedContentBlock uses this exact pattern:
arrow = "\u25bc" if is_expanded else "\u25b6"
# ...
if is_expanded:
    t.append(_indent_text(block.content, block.indent + "    "))
else:
    t.append(Text(block.indent + "    ...", style="dim"))
```

### Filter indicator pattern (rendering.py line 66-75):
```python
def _add_filter_indicator(text: Text, filter_name: str) -> Text:
    if filter_name not in FILTER_INDICATORS:
        return text
    symbol, color = FILTER_INDICATORS[filter_name]
    indicator = Text()
    indicator.append(symbol + " ", style=f"bold {color}")
    indicator.append(text)
    return indicator
```

## Import Paths
- `cc_dump.tui.rendering` - render_blocks, _render_text_content_collapsed (new)
- `cc_dump.tui.widget_factory` - TurnData.compute_relevant_keys
- `cc_dump.formatting` - RoleBlock, TextContentBlock (dataclass definitions)
- `cc_dump.palette` - PALETTE.filter_color(), PALETTE.filter_bg()
- `cc_dump.tui.custom_footer` - StyledFooter._init_palette_colors()

## Module Boundaries
- `rendering.py` is RELOADABLE -- hot-reload will pick up changes
- `app.py` is STABLE -- must use `import cc_dump.module` pattern (already does)
- `widget_factory.py` is RELOADABLE
- `custom_footer.py` is STABLE (but _init_palette_colors is called at module load)
- `palette.py` is RELOADABLE
