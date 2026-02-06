# Implementation Context: Sprint 2 - Delete LLM Code

## Files to DELETE
```
src/surview/token_counter.py
src/surview/analysis.py
tests/test_token_counter.py
tests/test_analysis.py
tests/test_store_token_counting.py
tests/test_tool_economics.py
tests/test_tool_economics_breakdown.py
tests/test_tool_rendering.py
```

## Import lines to REMOVE

### src/surview/formatting.py line 13
```python
# DELETE: from surview.analysis import TurnBudget, compute_turn_budget, tool_result_breakdown
```

### src/surview/store.py lines 11-13
```python
# DELETE: from surview.analysis import correlate_tools
# DELETE: from surview.token_counter import count_tokens
```

### src/surview/db_queries.py line 12
```python
# DELETE: from surview.analysis import ToolInvocation, ToolEconomicsRow, classify_model, HAIKU_BASE_UNIT, estimate_tokens
```

### src/surview/tui/panel_renderers.py line 7
```python
# DELETE: import surview.analysis
```

### src/surview/tui/widget_factory.py line 22
```python
# DELETE: import surview.analysis
```

## hot_reload.py updates
Remove from _RELOAD_ORDER:
```python
"surview.analysis",    # DELETED
```

## What NOT to delete yet
- formatting.py itself (rewritten in Sprint 4)
- store.py, schema.py, db_queries.py (rewritten in Sprint 6)
- har_recorder.py, har_replayer.py (rewritten in Sprint 7)
- tui/rendering.py, tui/event_handlers.py, tui/app.py (rewritten in Sprint 5)
- tui/panel_renderers.py, tui/widget_factory.py (rewritten in Sprint 5)
- test_formatting.py, test_har_*.py, test_visual_indicators.py (rewritten in Sprint 8)
