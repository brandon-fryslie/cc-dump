# Implementation Context: tool-correlation-summaries
Generated: 2026-01-30-110000
Source: EVALUATION-20260130.md

## File: src/cc_dump/formatting.py

### 1. Add fields to ToolUseBlock (line 92-96)

After Sprint 3 adds `detail`, add `tool_use_id`:
```python
@dataclass
class ToolUseBlock(FormattedBlock):
    """A tool_use content block."""
    name: str = ""
    input_size: int = 0
    msg_color_idx: int = 0
    detail: str = ""        # from Sprint 3
    tool_use_id: str = ""   # NEW: for correlation
```

### 2. Add fields to ToolResultBlock (line 100-104)

```python
@dataclass
class ToolResultBlock(FormattedBlock):
    """A tool_result content block."""
    size: int = 0
    is_error: bool = False
    msg_color_idx: int = 0
    tool_use_id: str = ""   # NEW: for correlation
    tool_name: str = ""     # NEW: for summary display
```

### 3. Modify format_request() message loop (line 336-378)

Add a tool_use_id -> (name, color_idx) lookup dict and a color counter. Build it incrementally since tool_use always precedes tool_result.

Before the message loop (after line 335):
```python
    # Tool correlation state (per-request, not persistent)
    tool_id_map: dict[str, tuple[str, int]] = {}  # tool_use_id -> (name, color_idx)
    tool_color_counter = 0
```

At the tool_use branch (line 359-363), extract tool_use_id and assign color:
```python
                elif btype == "tool_use":
                    name = cblock.get("name", "?")
                    tool_input = cblock.get("input", {})
                    input_size = len(json.dumps(tool_input))
                    tool_use_id = cblock.get("id", "")
                    detail = _tool_detail(name, tool_input)  # from Sprint 3
                    # Assign correlation color
                    tool_color_idx = tool_color_counter % MSG_COLOR_CYCLE
                    tool_color_counter += 1
                    if tool_use_id:
                        tool_id_map[tool_use_id] = (name, tool_color_idx)
                    blocks.append(ToolUseBlock(
                        name=name, input_size=input_size,
                        msg_color_idx=tool_color_idx,
                        detail=detail,
                        tool_use_id=tool_use_id,
                    ))
```

At the tool_result branch (line 364-373), look up name and color:
```python
                elif btype == "tool_result":
                    content_val = cblock.get("content", "")
                    if isinstance(content_val, list):
                        size = sum(len(json.dumps(p)) for p in content_val)
                    elif isinstance(content_val, str):
                        size = len(content_val)
                    else:
                        size = len(json.dumps(content_val))
                    is_error = cblock.get("is_error", False)
                    tool_use_id = cblock.get("tool_use_id", "")
                    # Look up correlated name and color
                    tool_name = ""
                    tool_color_idx = msg_color_idx  # fallback to message color
                    if tool_use_id and tool_use_id in tool_id_map:
                        tool_name, tool_color_idx = tool_id_map[tool_use_id]
                    blocks.append(ToolResultBlock(
                        size=size, is_error=is_error,
                        msg_color_idx=tool_color_idx,
                        tool_use_id=tool_use_id,
                        tool_name=tool_name,
                    ))
```

## File: src/cc_dump/tui/rendering.py

### 4. Update `_render_tool_result()` (line 166-175)

Replace with dual-mode rendering:
```python
def _render_tool_result(block: ToolResultBlock, filters: dict) -> Text | None:
    """Render tool result block. Shows full or summary based on tools filter."""
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]

    if filters.get("tools", False):
        # Full mode: detailed display
        label = "[tool_result:error]" if block.is_error else "[tool_result]"
        t = Text("  ")
        t.append(label, style="bold {}".format(color))
        if block.tool_name:
            t.append(" {}".format(block.tool_name))
        t.append(" ({} bytes)".format(block.size))
        return _add_filter_indicator(t, "tools")
    else:
        # Summary mode: compact, dimmed
        if block.tool_name:
            label = "[{}:error]".format(block.tool_name) if block.is_error else "[{}]".format(block.tool_name)
        else:
            label = "[tool_result:error]" if block.is_error else "[tool_result]"
        t = Text("  ")
        t.append(label, style="dim {}".format(color))
        t.append(" ({} bytes)".format(block.size), style="dim")
        return t
```

### 5. Update BLOCK_FILTER_KEY (line 279)

Change ToolResultBlock entry:
```python
    ToolResultBlock: None,  # Was "tools" -- now always visible (summary or full)
```

This means ToolResultBlock renders in both filter states. The renderer itself decides what to show.

### 6. No changes to _render_tool_use (line 155-163)

The tool_use renderer already reads `msg_color_idx`. Since we populate it with the correlation color instead of message color, it will automatically use the correlated color. No code change needed.

## File: tests/

### 7. Test tool_use_id population

```python
from cc_dump.formatting import format_request, ToolUseBlock, ToolResultBlock

def _make_state():
    return {
        "request_counter": 0,
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
    }

class TestToolCorrelation:
    def test_tool_use_id_populated(self):
        body = {
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "tu_123", "name": "Read", "input": {"file_path": "/a.txt"}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "tu_123", "content": "file contents"},
                ]},
            ]
        }
        blocks = format_request(body, _make_state())
        tool_uses = [b for b in blocks if isinstance(b, ToolUseBlock)]
        tool_results = [b for b in blocks if isinstance(b, ToolResultBlock)]
        assert tool_uses[0].tool_use_id == "tu_123"
        assert tool_results[0].tool_use_id == "tu_123"
        assert tool_results[0].tool_name == "Read"

    def test_color_correlation(self):
        body = {
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {}},
                    {"type": "tool_use", "id": "tu_2", "name": "Bash", "input": {}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "r1"},
                    {"type": "tool_result", "tool_use_id": "tu_2", "content": "r2"},
                ]},
            ]
        }
        blocks = format_request(body, _make_state())
        uses = {b.tool_use_id: b for b in blocks if isinstance(b, ToolUseBlock)}
        results = {b.tool_use_id: b for b in blocks if isinstance(b, ToolResultBlock)}
        # Matching pairs share color
        assert uses["tu_1"].msg_color_idx == results["tu_1"].msg_color_idx
        assert uses["tu_2"].msg_color_idx == results["tu_2"].msg_color_idx
        # Different pairs have different colors
        assert uses["tu_1"].msg_color_idx != uses["tu_2"].msg_color_idx
```

### 8. Test summary rendering

```python
from cc_dump.formatting import ToolResultBlock
from cc_dump.tui.rendering import _render_tool_result

class TestToolResultSummary:
    def test_full_mode_shows_name(self):
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": True})
        assert "Read" in result.plain
        assert "500 bytes" in result.plain

    def test_summary_mode_when_filter_off(self):
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": False})
        assert result is not None  # No longer returns None!
        assert "Read" in result.plain
        assert "500 bytes" in result.plain

    def test_summary_without_name(self):
        block = ToolResultBlock(size=500, msg_color_idx=0)
        result = _render_tool_result(block, {"tools": False})
        assert "tool_result" in result.plain
```

## Adjacent Patterns
- `correlate_tools()` in analysis.py:173-231 -- existing tool_use_id correlation logic (operates on raw messages, not IR blocks). The formatting layer approach is simpler because it builds the lookup during the single message iteration pass.
- `_render_tool_use` at rendering.py:155 -- existing tool renderer pattern with MSG_COLORS indexing.
- `BLOCK_FILTER_KEY` at rendering.py:269-290 -- existing filter key mapping. `TextContentBlock: None` is the precedent for always-visible blocks.

## Gotchas
- The `tool_id_map` is per-request (local to `format_request()`), NOT per-session. Each API request body contains a complete conversation history with all tool_use/tool_result pairs. The map will always find matches within a single request.
- If a tool_result references a tool_use_id that was not in any assistant message in the current request (e.g., truncated conversation), `tool_name` will be empty and `msg_color_idx` falls back to the message-position color. This is acceptable degradation.
- Changing BLOCK_FILTER_KEY for ToolResultBlock means `TurnData.compute_relevant_keys()` will no longer include "tools" for turns that only have ToolResultBlock (no ToolUseBlock). This is correct -- those turns will always render their ToolResultBlock regardless of tools filter state.
