# Definition of Done: filter-registry

- [ ] `grep -rn "expand\|headers\|tools\|system\|metadata\|stats\|economics\|timeline\|budget" src/cc_dump/palette.py src/cc_dump/tui/custom_footer.py` shows only references derived from registry, not hardcoded filter names
- [ ] Adding a test filter to the registry and NOT updating any consumer file causes a specific test to fail
- [ ] All existing tests pass
- [ ] `uv run pytest` passes
- [ ] `uvx ruff check src/` passes
