# Implementation Context: filter-perf-phase1
Generated: 2026-02-03-033800
Source: EVALUATION-20260203-033729.md
Plan: SPRINT-20260203-033800-filter-perf-phase1-PLAN.md

## File: src/cc_dump/tui/widget_factory.py

This is the ONLY production file modified in this sprint.

---

### cc-dump-ax6: Track changed turn range

**Target method: `ConversationView.rerender()` (line 551)**

Current code (line 580-590):
```python
changed = False
for td in self._turns:
    # Skip streaming turns during filter changes
    if td.is_streaming:
        continue
    overrides = self._overrides_for_turn(td.turn_index)
    if td.re_render(filters, console, width, expanded_overrides=overrides):
        changed = True

if changed:
    self._recalculate_offsets()
```

Replace with:
```python
first_changed = None
for idx, td in enumerate(self._turns):
    if td.is_streaming:
        continue
    overrides = self._overrides_for_turn(td.turn_index)
    if td.re_render(filters, console, width, expanded_overrides=overrides):
        if first_changed is None:
            first_changed = idx

if first_changed is not None:
    self._recalculate_offsets()
```

Also update the two subsequent `if changed` checks (lines 601, 605):
```python
# Line 601: was `if changed and anchor is not None:`
if first_changed is not None and anchor is not None:
    self._restore_anchor(anchor)

# Line 605: was `if changed and fresh_anchor is not None:`
if first_changed is not None and fresh_anchor is not None:
    if not self._scroll_to_anchor(fresh_anchor):
        self._saved_anchor = fresh_anchor
```

---

### cc-dump-e38: Cache per-turn widest strip width

**Step 1: Add field to TurnData dataclass (line 28-41)**

Insert after `_stable_strip_count` field (line 41):
```python
_widest_strip: int = 0  # cached max(s.cell_length for s in strips)
```

**Step 2: Add helper function (module level, before TurnData class)**

```python
def _compute_widest(strips: list) -> int:
    """Compute max cell_length across strips. O(m) but called once per assignment."""
    widest = 0
    for s in strips:
        w = s.cell_length
        if w > widest:
            widest = w
    return widest
```

**Step 3: Update TurnData.re_render() (line 78-82)**

After `self.strips, self.block_strip_map = ...` (line 78), add:
```python
self._widest_strip = _compute_widest(self.strips)
```

**Step 4: Update ConversationView.add_turn() (line 235-246)**

After `td = TurnData(...)` construction (line 235-240), add:
```python
td._widest_strip = _compute_widest(strips)
```

**Step 5: Update ConversationView.on_resize() (line 632-635)**

After `td.strips, td.block_strip_map = ...` (line 632), add:
```python
td._widest_strip = _compute_widest(td.strips)
```

**Step 6: Update ConversationView._refresh_streaming_delta()**

At line 299 (empty buffer path `td.strips = td.strips[:td._stable_strip_count]`), add:
```python
td._widest_strip = _compute_widest(td.strips)
```

At line 313 (delta render path `td.strips = td.strips[:td._stable_strip_count] + delta_strips`), add:
```python
td._widest_strip = _compute_widest(td.strips)
```

**Step 7: Update ConversationView._flush_streaming_delta() (line 333)**

After `td.strips = td.strips[:td._stable_strip_count] + delta_strips` (line 333), add:
```python
td._widest_strip = _compute_widest(td.strips)
```

**Step 8: Update ConversationView.append_streaming_block() (line 404)**

After `td.strips.extend(new_strips)` (line 404), add:
```python
td._widest_strip = _compute_widest(td.strips)
```

**Step 9: Update ConversationView.finalize_streaming_turn() (line 469)**

After `td.strips = strips` (line 469), add:
```python
td._widest_strip = _compute_widest(td.strips)
```

**Step 10: Update _recalculate_offsets() (line 209-223)**

Replace:
```python
def _recalculate_offsets(self):
    """Rebuild line offsets and virtual size."""
    offset = 0
    widest = 0
    for turn in self._turns:
        turn.line_offset = offset
        offset += turn.line_count
        for strip in turn.strips:
            w = strip.cell_length
            if w > widest:
                widest = w
    self._total_lines = offset
    self._widest_line = max(widest, self._last_width)
    self.virtual_size = Size(self._widest_line, self._total_lines)
    self._line_cache.clear()
```

With:
```python
def _recalculate_offsets(self):
    """Rebuild line offsets and virtual size."""
    self._recalculate_offsets_from(0)
```

(The actual logic moves to `_recalculate_offsets_from` -- see cc-dump-0oo below.)

**Step 11: Update _update_streaming_size() (line 341-364)**

Replace entire method body to delegate:
```python
def _update_streaming_size(self, td: TurnData):
    """Update total_lines and virtual_size for streaming turn."""
    self._recalculate_offsets()
```

This eliminates the near-duplicate code. The overhead is acceptable: O(n) integer comparisons per streaming delta vs O(n*m) strip property access previously.

---

### cc-dump-0oo: Incremental offset recalculation

**New method on ConversationView (insert after `_recalculate_offsets`)**

```python
def _recalculate_offsets_from(self, start_idx: int):
    """Rebuild line offsets and virtual size from start_idx onwards.

    For start_idx > 0, reuses offset from previous turn.
    Widest line is always recomputed from all turns (O(n) with cached _widest_strip).
    """
    turns = self._turns
    if start_idx > 0 and start_idx < len(turns):
        prev = turns[start_idx - 1]
        offset = prev.line_offset + prev.line_count
    else:
        offset = 0
        start_idx = 0

    for i in range(start_idx, len(turns)):
        turns[i].line_offset = offset
        offset += turns[i].line_count

    # Widest: O(n) integer comparisons with cached _widest_strip
    widest = 0
    for turn in turns:
        if turn._widest_strip > widest:
            widest = turn._widest_strip

    self._total_lines = offset
    self._widest_line = max(widest, self._last_width)
    self.virtual_size = Size(self._widest_line, self._total_lines)
    self._line_cache.clear()
```

**Update rerender() to use incremental (line 589-590)**

Change:
```python
if first_changed is not None:
    self._recalculate_offsets()
```
To:
```python
if first_changed is not None:
    self._recalculate_offsets_from(first_changed)
```

---

## File: tests/test_widget_arch.py

**New tests to add (append to end of file)**

### Test: _widest_strip accuracy after re_render

```python
class TestWidestStripCache:
    """Test _widest_strip caching on TurnData."""

    def test_widest_strip_set_after_re_render(self):
        """_widest_strip matches actual max strip cell_length after re_render."""
        from rich.console import Console
        blocks = [TextContentBlock(text="Short\nA much longer line of text here", indent="")]
        console = Console()
        filters = {}
        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()
        td.re_render(filters, console, 80, force=True)

        expected = max(s.cell_length for s in td.strips) if td.strips else 0
        assert td._widest_strip == expected
        assert td._widest_strip > 0

    def test_widest_strip_zero_for_empty_strips(self):
        """_widest_strip is 0 when all blocks filtered out."""
        from rich.console import Console
        blocks = [ToolUseBlock(name="test", input_size=10, msg_color_idx=0)]
        console = Console()
        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()
        # Tools not shown, summary line only
        td.re_render({"tools": False}, console, 80, force=True)
        # Even summary produces strips, so just verify cache matches
        expected = max(s.cell_length for s in td.strips) if td.strips else 0
        assert td._widest_strip == expected
```

### Test: incremental offset correctness

```python
class TestIncrementalOffsets:
    """Test _recalculate_offsets_from correctness."""

    def test_incremental_matches_full_recalc(self):
        """Incremental from index K produces same offsets as full recalc."""
        from textual.strip import Strip

        conv = ConversationView()
        # Build 5 turns with known strip counts
        for i in range(5):
            strip_count = (i + 1) * 2  # 2, 4, 6, 8, 10
            td = TurnData(
                turn_index=i,
                blocks=[],
                strips=[Strip.blank(80 + i * 10)] * strip_count,
                _widest_strip=80 + i * 10,
            )
            conv._turns.append(td)

        # Full recalc to establish baseline
        conv._recalculate_offsets()
        baseline_offsets = [t.line_offset for t in conv._turns]
        baseline_total = conv._total_lines
        baseline_widest = conv._widest_line

        # Modify turn 2 (change strip count)
        conv._turns[2].strips = [Strip.blank(90)] * 3  # was 6 strips, now 3
        conv._turns[2]._widest_strip = 90

        # Incremental from index 2
        conv._recalculate_offsets_from(2)
        incr_offsets = [t.line_offset for t in conv._turns]

        # Turns 0-1 offsets unchanged
        assert incr_offsets[0] == baseline_offsets[0]
        assert incr_offsets[1] == baseline_offsets[1]

        # Full recalc for comparison
        conv._recalculate_offsets()
        full_offsets = [t.line_offset for t in conv._turns]

        # Incremental and full must match
        assert incr_offsets == full_offsets

    def test_incremental_from_zero_matches_full(self):
        """_recalculate_offsets_from(0) is identical to _recalculate_offsets()."""
        from textual.strip import Strip

        conv = ConversationView()
        for i in range(3):
            td = TurnData(
                turn_index=i,
                blocks=[],
                strips=[Strip.blank(80)] * (i + 1),
                _widest_strip=80,
            )
            conv._turns.append(td)

        conv._recalculate_offsets_from(0)
        offsets_from = [t.line_offset for t in conv._turns]
        total_from = conv._total_lines

        conv._recalculate_offsets()
        offsets_full = [t.line_offset for t in conv._turns]
        total_full = conv._total_lines

        assert offsets_from == offsets_full
        assert total_from == total_full
```

### Test: first_changed tracking

Follow pattern from `TestTurnDataReRender` using the `_make_conv` / `_patch_scroll` helpers from `TestSavedScrollAnchor`. Test that toggling a filter affecting only turn 3 of 5 results in `_recalculate_offsets_from` being called with index 3. This can be verified by checking that turns 0-2 retain their original `line_offset` values while turns 3-4 are recomputed.

---

## Codebase patterns to follow

**Dataclass field style** (widget_factory.py line 28-41):
- Private fields use underscore prefix: `_widest_strip`, `_last_filter_snapshot`
- Default values inline: `_widest_strip: int = 0`
- Use `field(default_factory=...)` only for mutable defaults

**Method style** (widget_factory.py):
- Private methods use underscore prefix
- Docstrings use imperative mood, one-line summary
- Type hints in signature, not docstring

**Test style** (test_widget_arch.py):
- Class-based grouping by feature
- `from textual.strip import Strip` imported at method level when only needed there
- Direct `ConversationView()` construction without app context for unit tests
- Manual `TurnData` construction with `Strip.blank(width)` for controlled tests

**Import pattern** (widget_factory.py is reloadable):
- Module-level: `import cc_dump.tui.rendering` (not `from ... import`)
- Function-level: `from cc_dump.formatting import TextContentBlock` only inside methods
