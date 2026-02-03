# Sprint: filter-perf-phase1 - Phase 1 Filter Performance Optimizations
Generated: 2026-02-03-033800
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION
Source: EVALUATION-20260203-033729.md

## Sprint Goal
Eliminate O(n*m) full-scan overhead in filter rerenders and streaming updates by tracking changed turn ranges, caching per-turn widest strip widths, and recalculating offsets incrementally from the first changed turn.

## Scope
**Deliverables:**
- cc-dump-ax6: Track changed turn range during rerender (`first_changed` index)
- cc-dump-e38: Cache per-turn widest strip width (`_widest_strip` field on TurnData)
- cc-dump-0oo: Incremental offset recalculation from `first_changed` index

**Tickets:** cc-dump-ax6, cc-dump-e38, cc-dump-0oo (implement in this order)

## Work Items

### P0 [HIGH] cc-dump-ax6: Track changed turn range during rerender

**Dependencies**: None (foundation ticket)
**Spec Reference**: Beads ticket cc-dump-ax6 | **Status Reference**: EVALUATION-20260203-033729.md "cc-dump-ax6" section

#### Description
Replace the boolean `changed = False` / `changed = True` pattern in `ConversationView.rerender()` with a `first_changed: int | None` variable that captures the list index of the first turn whose `re_render()` returns True. This provides the foundation for cc-dump-0oo to skip unchanged prefix turns during offset recalculation.

#### Acceptance Criteria
- [ ] `rerender()` uses `first_changed: int | None` instead of `changed: bool`
- [ ] `first_changed` is set to the loop index (not `td.turn_index`) of the first turn where `td.re_render()` returns True
- [ ] When `first_changed is not None`, `_recalculate_offsets()` is called (preserving current behavior)
- [ ] When `first_changed is None`, `_recalculate_offsets()` is NOT called (preserving current behavior)
- [ ] All 23 existing widget tests pass without modification
- [ ] Scroll anchor restoration logic (`anchor`, `fresh_anchor`) still uses correct truthiness checks against `first_changed`

#### Technical Notes
- The loop in `rerender()` iterates `self._turns` in list order, so first True return is guaranteed earliest changed turn.
- `changed` is checked in 3 places after the loop (lines 589-607): the `_recalculate_offsets()` call, the `anchor` restore, and the `fresh_anchor` restore. All three must switch from `if changed:` to `if first_changed is not None:`.
- `first_changed` tracks list index (position in `self._turns`), not `td.turn_index` (semantic turn number). These are identical for non-filtered lists but using list index is correct for the offset recalculation use case.

---

### P0 [HIGH] cc-dump-e38: Cache per-turn widest strip width

**Dependencies**: None (independent, but enhances cc-dump-0oo)
**Spec Reference**: Beads ticket cc-dump-e38 | **Status Reference**: EVALUATION-20260203-033729.md "cc-dump-e38" section

#### Description
Add a `_widest_strip: int = 0` field to the `TurnData` dataclass. Update ALL 7 strip-assignment sites to recompute this cached value. Update `_recalculate_offsets()` and `_update_streaming_size()` to read per-turn `_widest_strip` instead of iterating every strip in every turn (converting O(n*m) to O(n) integer comparisons).

#### Acceptance Criteria
- [ ] `TurnData` has `_widest_strip: int = 0` field
- [ ] All 7 strip-assignment sites update `_widest_strip` (see Technical Notes for complete list)
- [ ] `_recalculate_offsets()` uses `turn._widest_strip` instead of inner strip loop
- [ ] `_update_streaming_size()` uses `turn._widest_strip` instead of inner strip loop
- [ ] All 23 existing widget tests pass without modification
- [ ] New test: after `TurnData.re_render()`, `_widest_strip` matches `max(s.cell_length for s in td.strips)` (or 0 if no strips)

#### Technical Notes
**Complete list of strip-assignment sites that must update `_widest_strip`:**

1. `TurnData.re_render()` (line 78) -- after `self.strips, self.block_strip_map = ...`
2. `ConversationView.add_turn()` (line 235) -- after TurnData constructor (strips passed in)
3. `ConversationView.on_resize()` (line 632) -- after `td.strips, td.block_strip_map = ...`
4. `ConversationView._refresh_streaming_delta()` (lines 299, 313) -- after `td.strips = ...`
5. `ConversationView._flush_streaming_delta()` (line 333) -- after `td.strips = ...`
6. `ConversationView.append_streaming_block()` (line 404) -- after `td.strips.extend(...)`
7. `ConversationView.finalize_streaming_turn()` (line 469) -- after `td.strips = strips`

**Helper pattern:** Add a static method or module function `_compute_widest(strips) -> int` to avoid duplicating `max(s.cell_length for s in strips) if strips else 0` at each site.

**`_recalculate_offsets()` change:** Replace inner `for strip in turn.strips:` loop with `turn._widest_strip`.

**`_update_streaming_size()` change:** Replace inner `for strip in turn.strips:` with `turn._widest_strip`. Also consider making `_update_streaming_size()` call `_recalculate_offsets()` to eliminate the near-duplicate code (evaluation recommendation #2).

**Edge case - widest-line-shrink:** When a turn's strips shrink (filter hides content), `_widest_strip` decreases. The global max must be recomputed from all turns. With per-turn cache this is O(n) integer comparisons -- acceptable for Phase 1. A too-wide value is cosmetically harmless (extra scroll space); a too-narrow value would clip content and must be avoided.

---

### P1 [HIGH] cc-dump-0oo: Incremental offset recalculation

**Dependencies**: cc-dump-ax6 (provides `first_changed` index)
**Spec Reference**: Beads ticket cc-dump-0oo | **Status Reference**: EVALUATION-20260203-033729.md "cc-dump-0oo" section

#### Description
Add `_recalculate_offsets_from(start_idx: int)` that skips offset recalculation for turns before `start_idx`. Wire `rerender()` to call `_recalculate_offsets_from(first_changed)` instead of `_recalculate_offsets()`. Keep `_recalculate_offsets()` as a thin wrapper calling `_recalculate_offsets_from(0)`.

#### Acceptance Criteria
- [ ] New method `_recalculate_offsets_from(start_idx: int)` exists on `ConversationView`
- [ ] For `start_idx > 0`, offset computation begins from `self._turns[start_idx - 1].line_offset + self._turns[start_idx - 1].line_count`
- [ ] For `start_idx == 0`, behavior is identical to current `_recalculate_offsets()`
- [ ] `_recalculate_offsets()` delegates to `_recalculate_offsets_from(0)` (no code duplication)
- [ ] `rerender()` passes `first_changed` (from cc-dump-ax6) to `_recalculate_offsets_from()`
- [ ] `_toggle_block_expand()` continues to work (calls full `_recalculate_offsets()`)
- [ ] `_update_streaming_size()` is also optimized or unified with `_recalculate_offsets()`
- [ ] All 23 existing widget tests pass without modification
- [ ] New test: create N turns, change turn K, verify offsets for turns 0..K-1 unchanged and turns K..N-1 correct

#### Technical Notes
**Offset portion** is truly incremental: read starting offset from `self._turns[start_idx - 1]` and iterate forward.

**Widest portion** is NOT truly incremental in Phase 1: global max must still scan all `_widest_strip` values (O(n) integers). True O(k) widest would require a max-heap or segment tree -- out of scope for Phase 1.

**`_line_cache.clear()`** remains a full clear in Phase 1. Selective cache invalidation is Phase 2 (cc-dump-0fe).

**`_update_streaming_size()` unification (evaluation recommendation #2):** The simplest approach is to make `_update_streaming_size()` call `_recalculate_offsets()` directly, since streaming is already per-delta and the overhead of O(n) integer comparisons per delta is negligible. This eliminates a maintenance hazard (duplicate logic that can diverge).

**Other callers of `_recalculate_offsets()`** that should NOT be changed to incremental:
- `add_turn()` -- always adds at end, full recalc is fine (could be optimized later)
- `on_resize()` -- all turns change, full recalc is correct
- `finalize_streaming_turn()` -- single event, full recalc is fine
- `_toggle_block_expand()` -- infrequent single-turn event
- `_rebuild_from_state()` -- full rebuild, full recalc is correct

## Dependencies
```
cc-dump-ax6 (first_changed tracking)
    |
    v
cc-dump-0oo (incremental offsets) <--- benefits from --- cc-dump-e38 (widest cache)
```
- cc-dump-ax6 has no dependencies -- implement first
- cc-dump-e38 has no dependencies -- can be implemented in parallel with ax6 or after
- cc-dump-0oo depends on cc-dump-ax6 for `first_changed`; benefits from cc-dump-e38 for O(n) vs O(n*m) widest calculation

**Recommended implementation order:** ax6 -> e38 -> 0oo

## Risks
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Missing a strip-assignment site for `_widest_strip` cache | Medium | Medium (stale widest value) | Complete enumeration in evaluation; add assertion in debug mode |
| `_update_streaming_size` diverges from `_recalculate_offsets` | Low | Medium (bugs in streaming path) | Unify by having `_update_streaming_size` call `_recalculate_offsets()` |
| Widest-line-shrink produces too-wide virtual size | Low | Low (cosmetic only -- extra scroll space) | Accept for Phase 1; O(n) integer scan is correct |
| Test breakage from dataclass field addition | Low | Low | `_widest_strip` has default value, no constructor changes needed |
