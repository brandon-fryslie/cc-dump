# Definition of Done: state-on-data

## Block-level collapsed field
- [ ] `grep -r "_expanded_overrides" src/` returns nothing
- [ ] `grep -r "_overrides_for_turn" src/` returns nothing
- [ ] `grep -r "expanded_overrides" src/cc_dump/tui/rendering.py` returns nothing
- [ ] `grep -r "expanded=" src/cc_dump/tui/rendering.py` returns nothing (no kwarg threading)
- [ ] Clicking a TrackedContentBlock toggles its collapsed state (visual verification)
- [ ] Clicking a TurnBudgetBlock toggles its collapsed state (visual verification)
- [ ] Global "budget" filter toggle still works (sets collapsed on all relevant blocks)
- [ ] `uv run pytest` passes
