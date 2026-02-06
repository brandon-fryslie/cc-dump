# Definition of Done: Sprint 6 - Database

## Exit Criteria
1. New schema creates cleanly: requests, blobs, request_blobs, requests_fts tables
2. SQLiteWriter accumulates events and commits complete request/response pairs
3. Large bodies are blobified (>512 bytes extracted to blobs table)
4. db_queries returns generic HTTP stats
5. No references to turns, tool_invocations, token counts, model names

## Verification
```bash
uv run pytest tests/test_schema.py tests/test_store.py -v  # (rewritten)
grep -rn "input_tokens\|output_tokens\|cache_read\|tool_invocations\|correlate_tools\|count_tokens" src/surview/schema.py src/surview/store.py src/surview/db_queries.py
# Should return zero hits
```
