# Implementation Context: tool-display-enrich
Generated: 2026-01-30-100000
Source: EVALUATION-20260130.md

## File: src/cc_dump/formatting.py

### 1. Add `detail` field to ToolUseBlock (line 92-96)

Current:
```python
@dataclass
class ToolUseBlock(FormattedBlock):
    """A tool_use content block."""
    name: str = ""
    input_size: int = 0
    msg_color_idx: int = 0
```

Add after `msg_color_idx`:
```python
    detail: str = ""  # Tool-specific enrichment (file path, skill name, command preview)
```

### 2. Add `_tool_detail()` helper function

Insert before `format_request()` (before line 285). Follow the pattern of `_get_timestamp()` which is a module-level helper.

```python
def _tool_detail(name: str, tool_input: dict) -> str:
    """Extract tool-specific detail string for display enrichment."""
    if name == "Read" or name == "mcp__plugin_repomix-mcp_repomix__file_system_read_file":
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return ""
        return _front_ellipse_path(file_path, max_len=40)
    if name == "Skill":
        return tool_input.get("skill", "")
    if name == "Bash":
        command = tool_input.get("command", "")
        if not command:
            return ""
        first_line = command.split("\n", 1)[0]
        if len(first_line) > 60:
            return first_line[:57] + "..."
        return first_line
    return ""


def _front_ellipse_path(path: str, max_len: int = 40) -> str:
    """Front-ellipse a file path: /a/b/c/d/file.ts -> ...c/d/file.ts"""
    if len(path) <= max_len:
        return path
    parts = path.split("/")
    # Build from the end until we exceed max_len
    result = ""
    for i in range(len(parts) - 1, -1, -1):
        candidate = "/".join(parts[i:])
        if len(candidate) + 3 > max_len:  # 3 for "..."
            break
        result = candidate
    if not result:
        # Even the filename alone is too long
        result = parts[-1]
        if len(result) > max_len - 3:
            result = result[-(max_len - 3):]
    return "..." + result
```

### 3. Populate detail in format_request() (line 359-363)

Current:
```python
                elif btype == "tool_use":
                    name = cblock.get("name", "?")
                    tool_input = cblock.get("input", {})
                    input_size = len(json.dumps(tool_input))
                    blocks.append(ToolUseBlock(name=name, input_size=input_size, msg_color_idx=msg_color_idx))
```

Change last line to:
```python
                    detail = _tool_detail(name, tool_input)
                    blocks.append(ToolUseBlock(name=name, input_size=input_size, msg_color_idx=msg_color_idx, detail=detail))
```

## File: src/cc_dump/tui/rendering.py

### 4. Update `_render_tool_use()` (line 155-163)

Current:
```python
def _render_tool_use(block: ToolUseBlock, filters: dict) -> Text | None:
    """Render tool use block."""
    if not filters.get("tools", False):
        return None
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[tool_use]", style="bold {}".format(color))
    t.append(" {} ({} bytes)".format(block.name, block.input_size))
    return _add_filter_indicator(t, "tools")
```

Change to:
```python
def _render_tool_use(block: ToolUseBlock, filters: dict) -> Text | None:
    """Render tool use block."""
    if not filters.get("tools", False):
        return None
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[tool_use]", style="bold {}".format(color))
    t.append(" {}".format(block.name))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.input_size))
    return _add_filter_indicator(t, "tools")
```

## File: tests/ (new test additions)

### 5. Tests for `_tool_detail` and `_front_ellipse_path`

Add to `tests/test_formatting.py` (or create new file if preferred). Follow the pattern in existing test files.

```python
from cc_dump.formatting import _tool_detail, _front_ellipse_path

class TestToolDetail:
    def test_read_file_path(self):
        result = _tool_detail("Read", {"file_path": "/Users/foo/bar/baz/file.ts"})
        assert "file.ts" in result
        assert result.startswith("...")

    def test_read_no_path(self):
        assert _tool_detail("Read", {}) == ""

    def test_skill_name(self):
        assert _tool_detail("Skill", {"skill": "commit"}) == "commit"

    def test_skill_no_name(self):
        assert _tool_detail("Skill", {}) == ""

    def test_bash_command(self):
        assert _tool_detail("Bash", {"command": "git status"}) == "git status"

    def test_bash_multiline(self):
        result = _tool_detail("Bash", {"command": "line1\nline2"})
        assert result == "line1"

    def test_bash_truncation(self):
        long_cmd = "x" * 100
        result = _tool_detail("Bash", {"command": long_cmd})
        assert len(result) <= 60
        assert result.endswith("...")

    def test_unknown_tool(self):
        assert _tool_detail("WebSearch", {"query": "test"}) == ""

class TestFrontEllipsePath:
    def test_short_path_unchanged(self):
        assert _front_ellipse_path("/a/b.ts", max_len=40) == "/a/b.ts"

    def test_long_path_ellipsed(self):
        result = _front_ellipse_path("/Users/foo/code/project/src/deep/file.ts", max_len=30)
        assert result.startswith("...")
        assert result.endswith("file.ts")
```

### 6. Test for rendering with detail

```python
from cc_dump.formatting import ToolUseBlock
from cc_dump.tui.rendering import _render_tool_use

class TestRenderToolUseDetail:
    def test_with_detail(self):
        block = ToolUseBlock(name="Read", input_size=100, msg_color_idx=0, detail="...path/file.ts")
        result = _render_tool_use(block, {"tools": True})
        plain = result.plain
        assert "Read" in plain
        assert "...path/file.ts" in plain
        assert "100 bytes" in plain

    def test_without_detail(self):
        block = ToolUseBlock(name="Read", input_size=100, msg_color_idx=0)
        result = _render_tool_use(block, {"tools": True})
        plain = result.plain
        assert "Read" in plain
        assert "100 bytes" in plain
```

## Adjacent Patterns to Follow
- `_get_timestamp()` at formatting.py:278 -- module-level helper function pattern
- `ToolUseBlock` construction at formatting.py:363 -- how blocks are created with kwargs
- `_render_tool_use` at rendering.py:155 -- how renderers build Rich Text with styled appends
- Test pattern in tests/test_formatting.py -- existing formatting test structure

## Import Paths
- `from cc_dump.formatting import ToolUseBlock, _tool_detail, _front_ellipse_path`
- `from cc_dump.tui.rendering import _render_tool_use`

## Gotchas
- `_tool_detail` and `_front_ellipse_path` must be importable from formatting.py (not underscore-hidden from tests -- Python convention allows test imports of private functions)
- The `tool_input` dict is already available at formatting.py:361 as a local variable -- no need to change the data flow
- StreamToolUseBlock (streaming variant, formatting.py:126) does NOT have access to tool input during streaming -- only the tool name is available at content_block_start. Detail enrichment is only for non-streaming ToolUseBlock.
