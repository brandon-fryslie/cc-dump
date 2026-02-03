# Sprint: message-collapse - User/Assistant Message Collapse Filters
Generated: 2026-02-03T18:00:00
Confidence: HIGH: 6, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION
Source: EVALUATION-20260203-180000.md

## Sprint Goal
Add two independent collapse/expand filters for User and Assistant messages, defaulting to collapsed (first 2 lines) with expand indicator arrow.

## Scope
**Deliverables:**
- Two new reactive filter states (`show_user_messages`, `show_assistant_messages`)
- Two new key bindings (`u` for user, `d` for assistant -- "d" since "a" is taken by stats)
- Modified `render_blocks()` to track current role and collapse TextContentBlock
- Expand indicator (arrow) on collapsed messages with >2 lines
- Footer integration with active-state styling
- Unit tests for collapse/expand behavior

## Work Items

### P0 - Add Filter State and Bindings to CcDumpApp

**Dependencies**: None
**Spec Reference**: User requirements (collapse/expand filters)
**Status Reference**: EVALUATION-20260203-180000.md "Filter System Architecture"

#### Description
Add two new reactive booleans to `CcDumpApp`: `show_user_messages` (default False) and `show_assistant_messages` (default False). Wire up key bindings, action handlers, reactive watchers, and include them in `active_filters` property.

#### Acceptance Criteria
- [ ] `show_user_messages = reactive(False)` exists on CcDumpApp
- [ ] `show_assistant_messages = reactive(False)` exists on CcDumpApp
- [ ] Key bindings `u` (toggle_user_messages) and `d` (toggle_assistant_messages) exist
- [ ] `active_filters` property includes `"user"` and `"assistant"` keys
- [ ] Reactive watchers call `_rerender_if_mounted()` on change

#### Technical Notes
- Follow exact pattern of existing filter toggles (show_headers, show_tools, etc.)
- Default False means collapsed (first 2 lines shown), True means expanded (full content)
- Binding descriptions should use pipe markers for styled letters: `"u|ser"`, `"a|d|vanced"` -- or simpler: `"u|ser msg"`, `"|d|etail asst"`

---

### P0 - Register "user" and "assistant" Filter Keys in Rendering Registry

**Dependencies**: None (can be done in parallel with app changes)
**Spec Reference**: User requirements
**Status Reference**: EVALUATION-20260203-180000.md "Block Types for Messages"

#### Description
Register `"user"` and `"assistant"` as filter keys for `TextContentBlock` in the rendering system. Since `TextContentBlock` is currently always-visible (`None` filter key), and the collapse is context-dependent (depends on preceding RoleBlock), the filter key must be registered at the `render_blocks()` level rather than in `_BLOCK_REGISTRY`.

The key insight: `TextContentBlock` itself remains filter_key=None in the registry (it's always rendered), but `render_blocks()` will apply role-based collapsing. The `relevant_filter_keys` for a turn must include `"user"` or `"assistant"` when the turn contains user/assistant messages.

#### Acceptance Criteria
- [ ] `TurnData.compute_relevant_keys()` includes `"user"` key when turn has user RoleBlock + TextContentBlock
- [ ] `TurnData.compute_relevant_keys()` includes `"assistant"` key when turn has assistant RoleBlock + TextContentBlock
- [ ] Filter key changes for user/assistant trigger `re_render()` on relevant turns
- [ ] Non-user/non-assistant turns are unaffected (no unnecessary re-renders)

#### Technical Notes
- `compute_relevant_keys()` currently uses `get_block_filter_key(type(block).__name__)` which returns None for TextContentBlock. Need to also scan for RoleBlock roles to add "user"/"assistant" keys.
- Alternative: add a new helper that scans blocks for role-text sequences.

---

### P0 - Implement Collapse Logic in render_blocks()

**Dependencies**: Filter key registration
**Spec Reference**: User requirements (first 2 lines, expand indicator)
**Status Reference**: EVALUATION-20260203-180000.md "Rendering Pipeline", "Expand/Collapse Pattern"

#### Description
Modify `render_blocks()` in `rendering.py` to track the current role context. When rendering a `TextContentBlock` that follows a `user` or `assistant` RoleBlock, check the corresponding filter. If the filter is off (collapsed), truncate to first 2 lines and prepend an expand indicator arrow. If the message has <=2 lines, show it in full without an arrow.

#### Acceptance Criteria
- [ ] TextContentBlock after USER RoleBlock: collapsed to 2 lines when `filters["user"]` is False
- [ ] TextContentBlock after ASSISTANT RoleBlock: collapsed to 2 lines when `filters["assistant"]` is False
- [ ] Expand indicator arrow (`\u25b6`) shown before collapsed text only when >2 lines exist
- [ ] No arrow shown when message has <=2 lines (full content always visible)
- [ ] When filter is True (expanded), full content shown with down arrow (`\u25bc`) if >2 lines
- [ ] System messages, tool results, and other blocks are unaffected
- [ ] Multiple TextContentBlocks under same role are each independently collapsed

#### Technical Notes
- Follow the existing collapse pattern from `_render_tracked_content()`: arrow + content + "..." or full content.
- Line count: use `block.text.splitlines()`. If len <= 2, always show full (no arrow needed).
- Implementation location: inside `render_blocks()` loop, track `current_role` variable updated on each RoleBlock.
- Create a new renderer wrapper `_render_text_content_collapsible()` that takes the role filter state.
- Do NOT modify `_render_text_content()` itself (it handles the always-visible case for non-role contexts).

---

### P1 - Integrate with Footer Styling

**Dependencies**: Filter state in app
**Spec Reference**: User requirements
**Status Reference**: EVALUATION-20260203-180000.md "Footer Bindings"

#### Description
Add "user" and "assistant" filter entries to:
1. `_build_filter_indicators()` in `rendering.py` for the colored bar indicators
2. `StyledFooter._init_palette_colors()` for the footer active-state CSS
3. `FilterStatusBar.update_filters()` for the status bar display

#### Acceptance Criteria
- [ ] Footer shows `u` and `d` bindings with correct styling
- [ ] Active state background color changes when filter is toggled on
- [ ] Filter indicators (colored bars) appear on collapsed/expanded content

#### Technical Notes
- Need to add filter colors to palette. Can reuse existing palette entries or add two new ones.
- Follow exact pattern of existing filter entries in `_init_palette_colors()`.

---

### P1 - Update TurnData Relevant Keys for Role-Based Filters

**Dependencies**: None
**Spec Reference**: User requirements
**Status Reference**: EVALUATION-20260203-180000.md "Filter relevance"

#### Description
Modify `TurnData.compute_relevant_keys()` to detect when a turn contains user or assistant text content and add the corresponding filter keys. This ensures that toggling user/assistant filters only triggers re-render on turns that actually contain those messages.

#### Acceptance Criteria
- [ ] Turn with USER RoleBlock + TextContentBlock has `"user"` in relevant_filter_keys
- [ ] Turn with ASSISTANT RoleBlock + TextContentBlock has `"assistant"` in relevant_filter_keys
- [ ] Turn with only tool blocks does not have `"user"` or `"assistant"` in relevant_filter_keys
- [ ] Turn with system-only content does not have `"user"` or `"assistant"` in relevant_filter_keys

#### Technical Notes
- Scan blocks list for RoleBlock followed by TextContentBlock sequences.
- Use class name strings for hot-reload safety (same pattern as existing code).

---

### P2 - Unit Tests for Collapse Behavior

**Dependencies**: All implementation items
**Spec Reference**: User requirements
**Status Reference**: EVALUATION-20260203-180000.md

#### Description
Add unit tests covering the collapse/expand behavior for user and assistant messages.

#### Acceptance Criteria
- [ ] Test: TextContentBlock after USER RoleBlock collapses to 2 lines when filter off
- [ ] Test: TextContentBlock after ASSISTANT RoleBlock collapses to 2 lines when filter off
- [ ] Test: No arrow indicator when message has <=2 lines
- [ ] Test: Arrow indicator present when message has >2 lines and collapsed
- [ ] Test: Full content shown when filter is on (expanded)
- [ ] Test: Toggling filter triggers re-render only on affected turns
- [ ] Test: Both filters work independently (user collapsed, assistant expanded)
- [ ] All existing 27+ widget tests continue to pass

#### Technical Notes
- Add tests to `tests/test_widget_arch.py` following existing patterns.
- Use `render_blocks()` directly with crafted block lists and filter dicts.
- Verify strip counts change appropriately between collapsed and expanded states.

## Dependencies
- P0 items can be implemented in parallel
- P1 items depend on P0 filter state being in place
- P2 tests depend on all implementation being complete

## Risks
- **Low**: Collapse logic in `render_blocks()` adds complexity to an already-complex function. Mitigated by keeping the role tracking minimal (single variable).
- **Low**: Hot-reload compatibility. Mitigated by using class name strings (existing pattern).
- **Low**: Performance impact. Adding role tracking to `render_blocks()` is O(1) per block -- negligible.
