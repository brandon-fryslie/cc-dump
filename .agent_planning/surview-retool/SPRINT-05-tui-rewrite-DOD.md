# Definition of Done: Sprint 5 - TUI Rewrite

## Exit Criteria
1. `uv run surview` starts without errors
2. New renderers display HTTP request/response blocks
3. JSON bodies are syntax-highlighted
4. Filter keys h/b/s/f work correctly
5. Stats panel shows generic HTTP metrics
6. No references to ToolEconomicsPanel, TimelinePanel, or any Claude-specific block types in TUI code
7. `uv run surview --replay <existing-har>` displays formatted data (if HAR rewrite done)

## Verification
- Start surview, configure as proxy, send HTTP requests through it
- Verify: request line, headers, body, response status, response body all display
- Toggle filters: h hides/shows headers, b hides/shows bodies, s hides/shows SSE events
- Stats panel updates with request count and timing

```bash
grep -rn "ToolEconomicsPanel\|TimelinePanel\|ToolUseBlock\|ToolResultBlock\|MetadataBlock\|TurnBudget\|StopReason" src/surview/tui/ --include="*.py"
# Should return zero hits
```
