# Sprint 2: delete-llm-code - Remove LLM-Specific Code
Generated: 2026-02-06
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Delete all Claude/LLM-specific modules, test files, and dead code. Reduce codebase before rewriting. The app will NOT be functional after this sprint — that's expected.

## Scope
**Deliverables:**
- Delete files that are 100% LLM-specific
- Delete LLM-specific test files
- Strip LLM-specific imports from files that will be rewritten in later sprints
- Update hot_reload.py to remove deleted modules from reload lists

## Work Items

### P0: Delete 100% LLM-specific modules
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `src/surview/token_counter.py` deleted
- [ ] `src/surview/analysis.py` deleted
- [ ] All imports of `token_counter` removed (store.py line 13)
- [ ] All imports of `analysis` removed (formatting.py line 13, tui/widget_factory.py, tui/panel_renderers.py, db_queries.py)
- [ ] hot_reload.py: remove "surview.analysis" from _RELOAD_ORDER

**Technical Notes:**
- analysis.py has NO dependents once formatting.py stops importing from it
- token_counter.py's only caller is store.py (count_tokens)
- Removing these breaks store.py and formatting.py, which will be rewritten in Sprints 4-5

### P1: Delete LLM-specific test files
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `tests/test_token_counter.py` deleted
- [ ] `tests/test_analysis.py` deleted
- [ ] `tests/test_store_token_counting.py` deleted
- [ ] `tests/test_tool_economics.py` deleted
- [ ] `tests/test_tool_economics_breakdown.py` deleted
- [ ] `tests/test_tool_rendering.py` deleted

**Technical Notes:**
- These tests ONLY test deleted code. No salvageable patterns — new tests will be written in Sprint 8.
- Keep: test_formatting.py (rewrite later), test_har_*.py (rewrite later), test_visual_indicators.py (rewrite later)

### P2: Stub broken imports to allow partial test runs
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] formatting.py: remove `from surview.analysis import ...` line, comment `# TODO: Sprint 4 rewrite`
- [ ] store.py: remove `from surview.token_counter import count_tokens` line
- [ ] store.py: remove `from surview.analysis import correlate_tools` line
- [ ] db_queries.py: remove `from surview.analysis import ...` line
- [ ] tui/panel_renderers.py: remove `import surview.analysis`
- [ ] tui/widget_factory.py: remove `import surview.analysis`
- [ ] Generic tests (test_router.py, test_sessions.py, test_hot_reload.py) still pass

**Technical Notes:**
- These files will be fully rewritten in later sprints. The goal here is just to unblock imports so the non-LLM tests can run.
- Don't bother fixing the broken functions — just remove the dead imports.

## Dependencies
- Sprint 1 (package renamed to surview)

## Risks
- **App won't start**: Expected. formatting.py's format_request() will break without analysis imports. This is fine — it's rewritten in Sprint 4.
- **Some tests will fail**: Expected. Only generic tests (router, sessions, hot_reload) need to pass.
