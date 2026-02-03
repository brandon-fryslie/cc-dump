# Definition of Done: filter-perf-phase1
Generated: 2026-02-03-033800
Status: READY FOR IMPLEMENTATION
Plan: SPRINT-20260203-033800-filter-perf-phase1-PLAN.md
Source: EVALUATION-20260203-033729.md

## Acceptance Criteria

### cc-dump-ax6: Track changed turn range during rerender
- [ ] `rerender()` uses `first_changed: int | None` instead of `changed: bool`
- [ ] `first_changed` captures list index of first turn where `re_render()` returns True
- [ ] All 3 post-loop checks (`_recalculate_offsets`, `anchor`, `fresh_anchor`) use `first_changed is not None`
- [ ] All 23 existing widget tests pass without modification

### cc-dump-e38: Cache per-turn widest strip width
- [ ] `TurnData` dataclass has `_widest_strip: int = 0` field
- [ ] All 7 strip-assignment sites update `_widest_strip`:
  - [ ] `TurnData.re_render()`
  - [ ] `ConversationView.add_turn()` (after constructor)
  - [ ] `ConversationView.on_resize()`
  - [ ] `ConversationView._refresh_streaming_delta()` (both paths: empty buffer trim and new delta)
  - [ ] `ConversationView._flush_streaming_delta()`
  - [ ] `ConversationView.append_streaming_block()` (extend path)
  - [ ] `ConversationView.finalize_streaming_turn()`
- [ ] `_recalculate_offsets()` reads `turn._widest_strip` instead of iterating strips
- [ ] `_update_streaming_size()` reads `turn._widest_strip` instead of iterating strips
- [ ] New test verifies `_widest_strip` matches actual max strip width after `re_render()`
- [ ] All 23 existing widget tests pass without modification

### cc-dump-0oo: Incremental offset recalculation
- [ ] `_recalculate_offsets_from(start_idx: int)` method exists
- [ ] `_recalculate_offsets()` delegates to `_recalculate_offsets_from(0)`
- [ ] `rerender()` calls `_recalculate_offsets_from(first_changed)` when `first_changed is not None`
- [ ] For `start_idx > 0`, starting offset derived from previous turn's `line_offset + line_count`
- [ ] `_update_streaming_size()` unified with or delegates to `_recalculate_offsets()`
- [ ] New test: N turns, change turn K, verify offsets 0..K-1 unchanged, K..N-1 correct
- [ ] All 23 existing widget tests pass without modification

### Cross-cutting
- [ ] Full test suite passes (`uv run pytest` -- 305+ tests)
- [ ] `just lint` passes with no new warnings
- [ ] Beads tickets updated: `bd update cc-dump-ax6 --status done --json`, same for e38 and 0oo
