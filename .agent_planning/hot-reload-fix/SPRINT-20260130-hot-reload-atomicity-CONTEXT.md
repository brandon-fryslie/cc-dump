# Implementation Context: hot-reload-atomicity

## Files to Modify

### `src/cc_dump/tui/app.py` (PRIMARY)

**`_replace_all_widgets()` (line 222-286)**: Restructure to create-before-remove pattern. Add `_replacing_widgets` flag.

**Widget accessors (lines 139-155)**: Change `query_one()` to try/except returning None.

**`_rerender_if_mounted()` (line 461-465)**: Add guard for `_replacing_widgets` flag, handle None from accessors.

**`_update_footer_state()` (line 165-171)**: Same None handling.

**All `action_*` methods**: Already have try/except in callers or should handle None.

### `tests/test_hot_reload.py`

Add test for widget replacement failure recovery.

## Key Constraints

- `app.py` is a STABLE module — no `from cc_dump.X import Y` for reloadable modules
- Must use `import cc_dump.tui.widget_factory` pattern (already correct)
- Textual `remove()` and `mount()` are sync-safe for DOM tree updates (async part is lifecycle events)

## Textual DOM Behavior (verified)

- `mount()` synchronously registers widget in DOM tree via `_register()`
- `remove()` sets `_pruning=True` and defers actual removal via `call_next()`
- `_register()` resets `_pruning=False` on the new widget
- No ID uniqueness enforcement on mount (only checks incoming batch for dupes)
- `query_one()` searches the live DOM tree

## Swap Strategy

Simplest correct approach:
1. Save all state
2. Create all new widgets with temp IDs (`*-new`)
3. Mount new widgets after header
4. Remove old widgets
5. Reassign real IDs to new widgets
6. Re-render

Wrapped in try/except — if creation fails at step 2, nothing has changed in DOM.
If mount fails at step 3, remove any partially mounted new widgets.
