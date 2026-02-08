# Sprint: state-on-data - Move Expand State onto FormattedBlock
Generated: 2026-02-06
Confidence: HIGH: 1, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Eliminate the per-block expand override system by moving `collapsed` state onto FormattedBlock, making expand/collapse a property of the data rather than a lookup in a distant dict.

## Scope
**Deliverables:**
- Add `collapsed: bool` field to FormattedBlock base class
- Remove `_expanded_overrides` dict and all parameter threading
- Simplify click handler to mutate block directly

**Out of scope:** Turn-level collapse is a future feature that benefits from this work but is not part of it.

## Work Items

### P0: Add collapsed field to FormattedBlock, remove override system
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `FormattedBlock` base class has `collapsed: bool = True` field (default collapsed)
- [ ] `TrackedContentBlock` and `TurnBudgetBlock` instances are created with appropriate default
- [ ] `ConversationView._expanded_overrides` dict is deleted
- [ ] `ConversationView._overrides_for_turn()` method is deleted
- [ ] `ConversationView._EXPANDABLE_BLOCK_TYPES` set is deleted (if it exists)
- [ ] `expanded_overrides` parameter removed from: `re_render()`, `render_turn_to_strips()`, `render_blocks()`, `render_block()`
- [ ] Individual renderers (`_render_tracked_content`, `_render_turn_budget`) read `block.collapsed` directly instead of receiving `expanded=` kwarg
- [ ] Click handler (`_toggle_block_expand`) mutates `block.collapsed` directly, then triggers single-turn re-render
- [ ] Cache invalidation still works — `block.collapsed` added to cache key
- [ ] All tests pass

**Technical Notes:**
- The block-level strip cache uses `id(block)` in its key. Mutating `block.collapsed` does not change `id(block)`. Fix: add `block.collapsed` to the cache key.
- The "global budget toggle clears all overrides" behavior becomes: iterate blocks, set `block.collapsed` to the new default. Simpler than the dict clear.
- FormattedBlock carrying UI state is an intentional decision. Document with a comment on the field.

## Dependencies
- Sprint 1 (dead-code-cleanup) must be complete — specifically the "expand" → "budget" rename
- Scroll simplification must be committed

## Risks
- Cache invalidation: mutating block.collapsed without changing block identity could serve stale cached strips. Mitigation: add collapsed to cache key.
- Hot-reload: block instances created before reload carry the old class. The `collapsed` field uses a default, so old instances won't have it. Mitigation: `getattr(block, 'collapsed', True)` in renderer, or handle in state restoration.
