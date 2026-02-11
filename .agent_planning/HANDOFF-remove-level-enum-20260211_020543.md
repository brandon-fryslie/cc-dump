# Handoff: Remove Level IntEnum and Fix Visibility Toggling

**Created**: 2026-02-11 02:05:43
**For**: Implementation agent
**Status**: ready-to-start

---

## Objective

Delete the `Level` IntEnum from `cc_dump/formatting.py` and replace it throughout the codebase with three orthogonal boolean dimensions (visible, full, expanded). Fix the broken visibility toggling system where Shift+number and Ctrl+Shift+number do not toggle the correct visibility dimension.

## Current State

### What's Been Done
- Identified the root cause: `active_filters` property hardcodes expanded state from `DEFAULT_EXPANDED[level]` instead of using `self._is_expanded[name]`
- Confirmed `_is_expanded` dict exists but has NO EFFECT on rendering
- Mapped the complete rendering pipeline and all Level usages
- Created forensic report showing only 3 of 5 visible states are reachable

### What's In Progress
- Plan to remove Level enum entirely (this handoff)

### What Remains
- Delete `Level` IntEnum class
- Replace all Level references with three-boolean tuples or data structure
- Update `TRUNCATION_LIMITS` to use boolean keys instead of Level
- Fix `active_filters` to use `_is_expanded`
- Update footer icons to work with new structure
- Update all tests
- Verify all 5 visible states are reachable

## Context & Background

### Why We're Doing This

The `Level` IntEnum (EXISTENCE=1, SUMMARY=2, FULL=3) implies an ordering that doesn't exist. The three dimensions are orthogonal:
- **visible/hidden** (toggled by number keys 1-7)
- **summary/full** (toggled by Shift+number)
- **collapsed/expanded** (toggled by Ctrl+Shift+number)

Using IntEnum allows nonsensical comparisons like `SUMMARY < FULL` and has led to repeated implementation bugs where Shift+number hides blocks instead of just toggling the summary/full dimension.

### Key Decisions Made

| Decision | Rationale | Date |
|----------|-----------|------|
| Three reactive dicts already exist | `_is_visible`, `_is_full`, `_is_expanded` are implemented correctly | 2026-02-10 |
| Problem is in `active_filters` only | It ignores `_is_expanded` and hardcodes from `DEFAULT_EXPANDED[level]` | 2026-02-11 |
| Delete Level entirely | Not just fix `active_filters` - remove the footgun | 2026-02-11 |

### Important Constraints

- **CRITICAL RULE**: Shift+number and Ctrl+Shift+number MUST NEVER hide blocks. Only number keys hide/show.
- Must maintain all existing keyboard shortcuts and their semantics
- Footer icons must display all 5 states correctly: · ▷ ▽ ▶ ▼
- All 199 existing tests must pass after refactor
- No changes to the FormattedBlock IR or formatting.py block types

## Acceptance Criteria

- [ ] `Level` IntEnum class deleted from `cc_dump/formatting.py`
- [ ] All imports of `Level` removed or replaced
- [ ] `TRUNCATION_LIMITS` keyed by `(visible, full, expanded)` boolean tuple instead of `(Level, expanded)`
- [ ] `active_filters` returns something that represents the three booleans (exact format TBD)
- [ ] All 5 visible states reachable through keyboard shortcuts:
  - Hidden (0 lines, · icon)
  - SUMMARY collapsed (3 lines, ▷ icon)
  - SUMMARY expanded (12 lines, ▽ icon)
  - FULL collapsed (5 lines, ▶ icon)
  - FULL expanded (unlimited, ▼ icon)
- [ ] Pressing Shift+number toggles summary↔full WITHOUT hiding
- [ ] Pressing Ctrl+Shift+number toggles collapsed↔expanded WITHOUT hiding
- [ ] Hiding then showing preserves the SHOW_STATE exactly
- [ ] All 199 tests pass
- [ ] Manual test shows all 4 non-dot footer icons appear during interaction

## Scope

### Files to Modify

**Core changes:**
- `src/cc_dump/formatting.py` - Delete `Level` class (lines 101-107), update `Category` enum if needed
- `src/cc_dump/tui/rendering.py` - Replace all Level references:
  - `TRUNCATION_LIMITS` dict (line 220) - change keys from `(Level, bool)` to `(bool, bool, bool)` or named tuple
  - `DEFAULT_EXPANDED` dict (line 229) - probably delete entirely
  - `BLOCK_STATE_RENDERERS` dict (line 757) - change keys from `(str, Level, bool)`
  - `_resolve_visibility()` function (line 281) - return new format instead of `(Level, bool)`
  - `render_turn_to_strips()` (line 963) - work with new format
- `src/cc_dump/tui/app.py` - Fix `active_filters` property (line 615):
  - Return dict mapping category name to three-boolean representation
  - Use `self._is_expanded[name]` instead of `DEFAULT_EXPANDED`
  - When hidden: always return (False, ?, ?) or equivalent meaning 0 lines
- `src/cc_dump/tui/custom_footer.py` - Update `_LEVEL_EXPANDED_ICONS` (line 19):
  - Change keys from `(int, bool)` to new three-boolean format
  - Keep the same 6 icons: · ▷ ▽ ▶ ▼ (plus duplicate · for consistency)
- `src/cc_dump/tui/widget_factory.py` - Update snapshot handling to use new format

**Test updates:**
- `tests/harness/assertions.py` - `get_vis_level()` helper (line 11) - update or replace
- `tests/test_textual_visibility.py` - Update Level references
- `tests/test_textual_content.py` - Update Level references
- `tests/test_input_modes.py` - Update Level references if any
- Any other test files importing Level

### Related Components

- `FormattedBlock.category` field - uses `Category` enum, NOT Level - leave unchanged
- Block-level `expanded` overrides - already work via `block.expanded` field - leave unchanged
- Search navigation expansion - already works via per-block overrides - leave unchanged

### Out of Scope

- Do NOT change the FormattedBlock IR structure in formatting.py
- Do NOT change how blocks are created or categorized
- Do NOT change the click-to-expand behavior in widget_factory.py
- Do NOT add new keyboard shortcuts (just fix existing ones)

## Implementation Approach

### Recommended Steps

1. **Define the new data structure** to replace `(Level, bool)` tuples:
   - Option A: Use `(visible: bool, full: bool, expanded: bool)` tuple directly
   - Option B: Create `@dataclass VisibilityState(visible, full, expanded)`
   - Option C: Keep filters as dict[str, tuple[bool, bool, bool]]
   - **Recommend Option A** for simplicity - named tuple or dataclass adds no value

2. **Update TRUNCATION_LIMITS first** (rendering.py line 220):
   ```python
   # Old: keyed by (Level, expanded)
   TRUNCATION_LIMITS: dict[tuple[Level, bool], int | None]

   # New: keyed by (visible, full, expanded)
   TRUNCATION_LIMITS: dict[tuple[bool, bool, bool], int | None] = {
       (False, False, False): 0,  # hidden
       (False, False, True):  0,  # hidden (expanded doesn't matter)
       (False, True, False):  0,  # hidden
       (False, True, True):   0,  # hidden
       (True, False, False):  3,  # SUMMARY collapsed
       (True, False, True):   12, # SUMMARY expanded
       (True, True, False):   5,  # FULL collapsed
       (True, True, True):    None, # FULL expanded (unlimited)
   }
   ```

3. **Delete DEFAULT_EXPANDED** - no longer needed since expanded is explicit in the tuple

4. **Update BLOCK_STATE_RENDERERS** keys (rendering.py line 757):
   ```python
   # Old: (type_name, Level, expanded)
   # New: (type_name, visible, full, expanded)
   BLOCK_STATE_RENDERERS: dict[tuple[str, bool, bool, bool], ...] = {
       ("TrackedContentBlock", False, False, False): _render_tracked_content_title,  # or whatever makes sense
       ("TurnBudgetBlock", False, False, False): _render_turn_budget_oneliner,
   }
   ```

   **NOTE**: These might need rethinking - "EXISTENCE expanded" doesn't map cleanly to booleans. May need special handling.

5. **Fix active_filters** (app.py line 615):
   ```python
   @property
   def active_filters(self):
       result = {}
       for _, name, _, _, _ in _CATEGORY_CONFIG:
           visible = self._is_visible[name]
           full = self._is_full[name]
           expanded = self._is_expanded[name]
           # When hidden, expanded doesn't matter - will render 0 lines either way
           result[name] = (visible, full, expanded)
       return result
   ```

6. **Update _resolve_visibility** (rendering.py line 281):
   ```python
   def _resolve_visibility(block, filters) -> tuple[bool, bool, bool]:
       cat = get_category(block)
       if cat is None:
           return (True, True, True)  # always visible, full, expanded
       visible, full, expanded = filters[cat.value]
       # Per-block override
       if block.expanded is not None:
           expanded = block.expanded
       return (visible, full, expanded)
   ```

7. **Update footer icons** (custom_footer.py line 19):
   ```python
   _VIS_ICONS = {
       # Format: (visible, full, expanded) -> icon
       (False, False, False): "·",  # hidden
       (False, False, True):  "·",  # hidden
       (False, True, False):  "·",  # hidden
       (False, True, True):   "·",  # hidden
       (True, False, False):  "▷",  # SUMMARY collapsed
       (True, False, True):   "▽",  # SUMMARY expanded
       (True, True, False):   "▶",  # FULL collapsed
       (True, True, True):    "▼",  # FULL expanded
   }
   ```

8. **Update all test imports and assertions** - replace `Level.EXISTENCE/SUMMARY/FULL` references

9. **Delete the Level class** from formatting.py (lines 101-107) - do this LAST after all references removed

### Patterns to Follow

- **Use tuple unpacking** for clarity: `visible, full, expanded = filters[name]` instead of `filters[name][0]`
- **Comment the tuple order** wherever it's not obvious: `# (visible, full, expanded)`
- **Keep the three reactive dicts unchanged** - they're already correct
- **Follow the existing reactive watcher pattern** - watchers call `_on_vis_state_changed()`

### Known Gotchas

- **Snapshot comparison in widget_factory.py**: Currently compares `(Level, bool)` tuples. After change, will compare `(bool, bool, bool)` tuples. Should still work via equality.
- **Search state save/restore** (app.py line 1232): Saves/restores all three dicts. Should work unchanged.
- **BLOCK_STATE_RENDERERS sparse entries**: Only 2 custom renderers exist. May need to rethink what "EXISTENCE expanded" means with booleans. Might be: render title when `visible=False` but other dimensions don't matter? Or remove these entirely?
- **Tests using `get_vis_level()`**: This helper derives a Level from the dicts. After deleting Level, either:
  - Change tests to check the three booleans directly
  - Or keep a helper that returns string labels like "hidden", "summary-collapsed", etc.

## Reference Materials

### Planning Documents

- `.claude/plans/encapsulated-doodling-barto.md` - Current plan (outdated - only fixes `active_filters`)
- This handoff - Comprehensive removal plan

### Beads Issues

- `cc-dump-2c1` - "Fix level/expanded state toggling" (currently closed, reopen for this work)

### Codebase References

**Key files with Level usage:**
- `src/cc_dump/formatting.py` - Level class definition
- `src/cc_dump/tui/rendering.py` - Heavy Level usage in rendering pipeline
- `src/cc_dump/tui/app.py` - `active_filters` property broken due to Level indirection
- `src/cc_dump/tui/custom_footer.py` - Footer icon mapping uses Level as int
- `tests/harness/assertions.py` - Test helper derives Level from app state

**Forensic investigation results:**
- Only 3 of 5 visible states currently reachable (EXISTENCE, SUMMARY collapsed, FULL expanded)
- `_is_expanded` dict exists but has zero effect on rendering
- Footer defines 6 icons but only shows 3 (·, ▷, ▼)
- TRUNCATION_LIMITS defines all 6 states correctly

### External Resources

- Python dataclasses docs - if we decide to use a named structure instead of bare tuple
- Textual reactive system docs - for understanding watcher behavior

## Questions & Blockers

### Open Questions

- [ ] Should we use bare tuples `(bool, bool, bool)` or create a `VisibilityState` dataclass/namedtuple?
- [ ] How to handle BLOCK_STATE_RENDERERS with the new format? The current `(type, EXISTENCE, True)` entries don't map cleanly.
- [ ] Should `get_vis_level()` test helper be deleted or adapted to return string labels?

### Current Blockers

None - ready to implement once questions answered.

### Need User Input On

- Preferred data structure for replacing `(Level, bool)`: bare tuple vs named structure
- How to handle the 2 BLOCK_STATE_RENDERERS entries for "EXISTENCE expanded"

## Testing Strategy

### Existing Tests

- `tests/test_textual_visibility.py` - 12 tests for visibility toggles
- `tests/test_textual_content.py` - 4 tests for content filtering
- `tests/test_input_modes.py` - 12 tests for keyboard input
- Coverage: All visibility logic covered

### New Tests Needed

After refactor, existing tests should validate the fix IF they're updated to use new format:
- [ ] All 5 visible states reachable (verify icons: ·, ▷, ▽, ▶, ▼)
- [ ] Shift+number never hides blocks
- [ ] Ctrl+Shift+number never hides blocks
- [ ] Hide/show preserves SHOW_STATE

No NEW test files needed - just update existing tests.

### Manual Testing

After implementation:
- [ ] Run `uv run cc-dump --replay latest`
- [ ] Press number keys: verify hide/show works, icon changes to ·
- [ ] Press Shift+4: verify tools toggle ▷↔▶ WITHOUT hiding
- [ ] Press Ctrl+Shift+4: verify arrow direction toggles (▷→▽ or ▶→▼) WITHOUT hiding
- [ ] Hide, toggle detail/expand, show: verify exact state restoration
- [ ] Verify all 4 non-dot icons appear: ▷ ▽ ▶ ▼

## Success Metrics

- `grep -r "from cc_dump.formatting import Level" src/ tests/` returns 0 results
- `uv run pytest` - all 548 tests pass (549 after removing obsolete test)
- Manual test shows all 5 states reachable and all 4 non-dot icons displayed
- No `IntEnum` comparison bugs possible (can't compare bools with < >)
- Code is simpler and more explicit about the three orthogonal dimensions

---

## Next Steps for Agent

**Immediate actions**:
1. Read rendering.py lines 220-233 (TRUNCATION_LIMITS, DEFAULT_EXPANDED) - understand current structure
2. Read app.py lines 613-633 (active_filters) - see how Level is currently derived
3. Decide: bare tuple vs dataclass for new format (recommend bare tuple)

**Before starting implementation**:
- [ ] Decide on data structure for `(visible, full, expanded)`
- [ ] Decide how to handle BLOCK_STATE_RENDERERS (maybe delete the 2 entries?)
- [ ] Run `grep -r "Level" src/ tests/` to find ALL references

**Implementation order**:
1. Update TRUNCATION_LIMITS keys to `(bool, bool, bool)`
2. Update active_filters to return `(bool, bool, bool)` tuples
3. Update _resolve_visibility to work with new format
4. Update render_turn_to_strips to use new TRUNCATION_LIMITS keys
5. Update footer icons
6. Update BLOCK_STATE_RENDERERS or delete the 2 custom entries
7. Update all test files
8. Delete Level class last
9. Run tests, verify all pass
10. Manual test all 5 states

**When complete**:
- [ ] Update beads issue cc-dump-2c1 with completion status
- [ ] Commit with message: "refactor: remove Level IntEnum, use three orthogonal booleans"
- [ ] Mark this handoff as complete
