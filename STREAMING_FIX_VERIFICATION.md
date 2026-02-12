# Streaming Text Display Fix - Verification Guide

## What Was Fixed

**Issue**: Streaming text output from Claude (live assistant response) was not being displayed in the TUI during streaming.

**Root Cause**: Category-based filter in `append_streaming_block()` was preventing TextDeltaBlocks from being rendered during streaming.

**Solution**: Removed the category filter from `append_streaming_block()` in `src/cc_dump/tui/widget_factory.py` (lines 539-545).

## Automated Verification

```bash
# All tests pass (595 tests)
uv run pytest tests/ -q

# Streaming-specific test passes
uv run pytest tests/test_tui_integration.py::TestConversationView::test_conversation_view_handles_streaming -v
```

✅ **Status**: All automated tests pass.

## Manual Verification Steps

### Option 1: Live Proxy Mode

```bash
# Terminal 1: Start cc-dump
just run
# Note the assigned port (e.g., "Proxy listening on http://127.0.0.1:58972")

# Terminal 2: Make a request through the proxy
ANTHROPIC_BASE_URL=http://127.0.0.1:<PORT> claude
# Ask Claude a question, e.g., "Write a haiku about streaming text"
```

**Expected behavior:**
1. ✅ Streaming text appears incrementally in TUI as Claude responds
2. ✅ Text is formatted as Markdown (code blocks, lists, bold/italic work)
3. ✅ Follow mode auto-scrolls to show new streaming content
4. ✅ No errors in logs panel (press `ctrl+l` to view logs)

### Option 2: Replay Mode (if HAR recordings available)

```bash
# Find a recording with streaming content
ls -lth ~/.cc-dump/recordings/

# Replay a recording
cc-dump --replay <path-to-har-file>
```

**Expected behavior:**
- Same as live mode above

## Technical Details

### What Changed

**Before** (broken):
```python
# Filter: only render USER and ASSISTANT content during streaming
from cc_dump.formatting import Category
block_category = cc_dump.tui.rendering.get_category(block)
if block_category not in (Category.USER, Category.ASSISTANT, None):
    # Skip rendering (but keep in blocks for finalize). None = always visible (ErrorBlock etc)
    return
```

**After** (fixed):
```python
# Removed - all blocks now render during streaming
```

### Why This Works

1. **During streaming**: All blocks (TextDelta, ToolUse, etc.) now render immediately
2. **After finalization**: Category-based filtering still applies via `finalize_streaming_turn()` which does a full re-render with proper visibility filters
3. **Result**: Users see streaming text as it arrives, and final display respects visibility settings

### Block Types That Benefit

- `TextDeltaBlock` - Primary fix target (assistant response text)
- `ToolUseBlock` - Tool calls during streaming
- `RoleBlock` - Role indicators
- `ErrorBlock` - Errors during streaming (already had special case for None category)

## Verification with Different Visibility Levels

The fix preserves correct category filtering after finalization:

```bash
# Start cc-dump and make a request
# During streaming: everything visible
# After completion: press visibility keys

1  # Toggle headers visibility
2  # Toggle user visibility
3  # Toggle assistant visibility (should show/hide the streamed text)
4  # Toggle tools visibility
5  # Toggle system visibility
```

**Expected**: Finalized turns respect visibility settings, streaming is always visible.

## Files Modified

- `src/cc_dump/tui/widget_factory.py` - Removed lines 539-545 from `append_streaming_block()`

## Related Architecture

See `ARCHITECTURE.md` for details on:
- Two-stage pipeline (formatting → rendering)
- Event flow (proxy → router → handlers → rendering)
- Virtual rendering system
- 3-level visibility system
