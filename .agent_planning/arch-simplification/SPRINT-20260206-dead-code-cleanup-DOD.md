# Definition of Done: dead-code-cleanup

## Verification
- [ ] `grep -r "DiffBlock" src/` returns only `make_diff_lines` references (no class def, no imports)
- [ ] `grep -r "LogBlock" src/` returns nothing
- [ ] `grep -r "get_model_economics" src/` returns nothing
- [ ] `grep -r '"expand"' src/cc_dump/` returns no filter-related hits (only unrelated string uses if any)
- [ ] `uv run pytest` passes
- [ ] `uvx ruff check src/` passes
- [ ] Each deliverable is a separate, clean commit
