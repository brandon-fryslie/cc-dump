# Implementation Context: dead-code-cleanup

## Dead Code Locations

### DiffBlock
- Class definition: `formatting.py:84` (class DiffBlock(FormattedBlock))
- NOT instantiated anywhere — `DiffBlock(` does not appear as a constructor call
- `make_diff_lines()` at `formatting.py:326` is USED by `rendering.py:633` — keep the function

### LogBlock
- Class definition: `formatting.py:201`
- Import: `rendering.py:33`
- Renderer: `rendering.py:332` (`_render_log`)
- BLOCK_RENDERERS entry: `rendering.py` dict
- BLOCK_FILTER_KEY entry: `rendering.py` dict
- NOT instantiated anywhere — `LogBlock(` does not appear as a constructor call
- LogsPanel widget uses Rich Text objects directly

### get_model_economics
- Function: `db_queries.py:276-317`
- Not called anywhere in the codebase

## Filter Rename Locations

All 5 sites where "expand" appears as a filter name:

1. **palette.py:66-75** — `_FILTER_INDICATOR_INDEX = { ... "expand": 5, ... }`
2. **app.py** — `show_expand = reactive(False)` property + `active_filters` property dict
3. **custom_footer.py:72-81** — maps action name to filter key
4. **rendering.py** — `BLOCK_FILTER_KEY` maps `"TurnBudgetBlock": "expand"`
5. **widget_factory.py** — references in expand override logic, FilterStatusBar

Also check: keybinding definition (likely in app.py or custom_footer.py action bindings).

## Token Estimation

- `analysis.py:estimate_tokens()` — `len(text) // 4`, used for real-time TurnBudget display
- `token_counter.py:count_tokens()` — tiktoken, used for DB storage in store.py
