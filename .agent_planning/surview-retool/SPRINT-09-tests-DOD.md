# Definition of Done: Sprint 9 - Tests

## Exit Criteria
1. `uv run pytest` — all tests pass (zero failures)
2. Test coverage exists for: proxy events, formatting blocks, rendering, store, HAR record/replay
3. Generic tests (router, sessions, hot_reload, scroll_nav, widget_arch) pass with updated imports
4. No test files reference Claude-specific types or API payloads

## Verification
```bash
uv run pytest -v
uv run pytest --tb=short 2>&1 | tail -5  # summary line shows 0 failures
grep -rn "ToolUse\|ToolResult\|MetadataBlock\|TurnBudget\|correlate_tools\|token_counter\|anthropic\|claude" tests/ --include="*.py"
# Should return zero hits (or only in comments explaining the retool)
```
