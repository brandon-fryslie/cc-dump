# Definition of Done: Sprint 1 - Rename Package

## Exit Criteria
1. `git mv src/cc_dump src/surview` committed
2. `uv run pytest` — all tests pass (except pre-existing test_format_response_event_message_start)
3. `uv run surview --help` works
4. `grep -r "cc_dump" src/ tests/` returns zero hits
5. `grep -r "cc-dump" src/ tests/ pyproject.toml justfile` returns zero hits (except git URLs if unchanged)
6. `uv run python -c "import surview"` succeeds

## Verification Commands
```bash
uv run pytest
uv run surview --help
grep -rn "cc_dump" src/ tests/ --include="*.py" | head -20
grep -rn "cc-dump" src/ tests/ pyproject.toml justfile | head -20
```
