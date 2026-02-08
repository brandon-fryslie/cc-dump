# Implementation Context: state-on-data

## Current Expand Override Flow (to be eliminated)

```
ConversationView._expanded_overrides: dict[(turn_idx, block_idx), bool]
  → _overrides_for_turn(turn_index) extracts {block_idx: bool} for one turn
    → TurnData.re_render(expanded_overrides=...)
      → render_turn_to_strips(expanded_overrides=...)
        → render_blocks(expanded_overrides=...)
          → render_block(expanded=bool_or_none)
            → _render_tracked_content(expanded=...)
            → _render_turn_budget(expanded=...)
```

## Target Flow

```
block.collapsed (bool field on FormattedBlock)
  → render_block() reads block.collapsed directly
    → _render_tracked_content() reads block.collapsed
    → _render_turn_budget() reads block.collapsed
```

## Key Files to Modify

### formatting.py
- Add `collapsed: bool = True` to FormattedBlock dataclass
- TrackedContentBlock and TurnBudgetBlock inherit it (default collapsed=True means "show summary")

### rendering.py
- Remove `expanded_overrides` parameter from `render_blocks()` and `render_turn_to_strips()`
- Remove `expanded=` parameter from `render_block()` and individual renderers
- Read `block.collapsed` directly in `_render_tracked_content()` and `_render_turn_budget()`
- Update cache key: replace `expand_override` component with `block.collapsed`

### widget_factory.py
- Delete `_expanded_overrides` dict from ConversationView.__init__
- Delete `_overrides_for_turn()` method
- Delete `_EXPANDABLE_BLOCK_TYPES` (if exists)
- Simplify `_toggle_block_expand()`: just flip `block.collapsed` and re-render turn
- Simplify `rerender()`: no longer needs to pass overrides
- Remove override-clearing logic from global filter toggle handler

## Cache Key Change

Current: `(id(block), width, filter_state, expand_override)`
New: `(id(block), width, filter_state, block.collapsed)`

This works because `id(block)` is stable (blocks are stored in TurnData.blocks and not recreated) and `block.collapsed` captures the current state.

## Hot-Reload Consideration

Blocks created before a hot-reload won't have the `collapsed` field if the old FormattedBlock class didn't define it. During `_rebuild_from_state()`, blocks are recreated from saved state, so this is handled. For the transient period between reload and rebuild, use `getattr(block, 'collapsed', True)` as a safety net in the renderer.
