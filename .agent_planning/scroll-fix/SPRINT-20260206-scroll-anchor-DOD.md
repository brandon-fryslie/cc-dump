# Definition of Done: scroll-anchor

## Verification Criteria

### Automated
1. `uv run pytest tests/test_widget_arch.py -v` — 37/37 pass
2. `uv run pytest -x -q` — full suite passes (excluding known-flaky PTY)
3. `grep -r "_saved_anchor\|_compute_anchor_from_scroll\|_scroll_to_anchor" src/` — no matches
4. `python -c "import cc_dump.formatting"` — no errors

### Manual (optional, for user validation)
5. Replay a HAR file, scroll to middle, toggle filters h/t/s/e/m — viewport stays at same turn
6. Toggle filter A, scroll elsewhere, toggle filter B — no jump back to pre-A position
7. In follow mode, toggle any filter — stays at bottom

## Done When
- All automated checks pass
- `git status` shows clean working tree
- Changes are on `bmf_fix_missing_assistant_header` branch
