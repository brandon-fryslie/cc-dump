# Definition of Done: Sprint 4 - Formatting IR

## Exit Criteria
1. formatting.py contains only generic HTTP block types (no Claude-specific blocks)
2. format_request() accepts (method, url, headers, body_bytes, state) and returns blocks
3. format_response_body() detects content type and creates appropriate block
4. JSON bodies are pretty-printed in JsonBodyBlock
5. No imports from analysis.py or token_counter.py
6. Unit tests for new format functions pass

## Verification Commands
```bash
uv run pytest tests/test_formatting.py -v  # (rewritten tests)
grep -n "ToolUse\|ToolResult\|MetadataBlock\|SystemLabel\|TurnBudget\|StopReason\|StreamInfo\|StreamToolUse" src/surview/formatting.py  # should return nothing
```
