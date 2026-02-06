# Definition of Done: Sprint 2 - Delete LLM Code

## Exit Criteria
1. `src/surview/token_counter.py` and `src/surview/analysis.py` do not exist
2. 6 LLM-specific test files deleted
3. No remaining imports of `token_counter` or `analysis` in any source file
4. `uv run pytest tests/test_router.py tests/test_sessions.py` passes
5. `grep -rn "tiktoken" src/` returns zero hits
6. tiktoken not in pyproject.toml dependencies (done in Sprint 1)

## Verification Commands
```bash
test ! -f src/surview/token_counter.py && echo "OK: token_counter deleted"
test ! -f src/surview/analysis.py && echo "OK: analysis deleted"
grep -rn "token_counter\|from surview.analysis\|import surview.analysis" src/ --include="*.py"
uv run pytest tests/test_router.py tests/test_sessions.py -v
```
