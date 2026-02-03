# Implementation Context: query-panel-update
Generated: 2026-02-03-130000
Source: EVALUATION-20260202.md
Confidence: HIGH

## ToolEconomicsRow Dataclass

### File: `src/cc_dump/analysis.py`
**Insert after `ToolAggregates` class (after line 172):**

```python
@dataclass
class ToolEconomicsRow:
    """Per-tool economics data for the panel display."""
    name: str = ""
    calls: int = 0
    input_tokens: int = 0
    result_tokens: int = 0
    cache_read_tokens: int = 0
    norm_cost: float = 0.0
```

No additional methods needed -- norm_cost is computed in the query layer.

---

## get_tool_economics() Query

### File: `src/cc_dump/db_queries.py`

**Add import** at top (line 3): `from cc_dump.analysis import ToolEconomicsRow, classify_model, ModelPricing, HAIKU_BASE_UNIT`

Note: `estimate_tokens` import on line 12 can be removed entirely since Sprint 1 removes its usage.

**Add new function** after `get_tool_invocations()` (after line 109):

```python
def get_tool_economics(db_path: str, session_id: str) -> list:
    """Query per-tool economics with real token counts and cache attribution.

    Returns list of ToolEconomicsRow with:
    - Real token counts from tool_invocations (input_tokens, result_tokens)
    - Proportional cache attribution from parent turn
    - Normalized cost using model pricing
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        # Fetch per-invocation data with turn-level context
        cursor = conn.execute("""
            SELECT
                ti.tool_name,
                ti.input_tokens,
                ti.result_tokens,
                t.model,
                t.input_tokens as turn_input,
                t.cache_read_tokens as turn_cache_read,
                t.id as turn_id
            FROM tool_invocations ti
            JOIN turns t ON ti.turn_id = t.id
            WHERE t.session_id = ?
            ORDER BY ti.id
        """, (session_id,))

        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    # Compute per-turn total tool input tokens (for proportional cache attribution)
    turn_tool_totals = {}  # turn_id -> sum of tool input_tokens
    for tool_name, input_tokens, result_tokens, model, turn_input, turn_cache_read, turn_id in rows:
        turn_tool_totals[turn_id] = turn_tool_totals.get(turn_id, 0) + input_tokens

    # Aggregate by tool name
    by_name = {}  # tool_name -> {calls, input_tokens, result_tokens, cache_read, cost_sum}
    for tool_name, input_tokens, result_tokens, model, turn_input, turn_cache_read, turn_id in rows:
        if tool_name not in by_name:
            by_name[tool_name] = {
                "calls": 0, "input_tokens": 0, "result_tokens": 0,
                "cache_read": 0, "norm_cost": 0.0,
            }
        agg = by_name[tool_name]
        agg["calls"] += 1
        agg["input_tokens"] += input_tokens
        agg["result_tokens"] += result_tokens

        # Proportional cache attribution
        turn_total = turn_tool_totals.get(turn_id, 0)
        if turn_total > 0 and turn_cache_read > 0:
            share = input_tokens / turn_total
            agg["cache_read"] += int(turn_cache_read * share)

        # Norm cost contribution
        _, pricing = classify_model(model)
        agg["norm_cost"] += (
            input_tokens * (pricing.base_input / HAIKU_BASE_UNIT)
            + result_tokens * (pricing.output / HAIKU_BASE_UNIT)
        )

    # Build result list sorted by norm_cost descending
    result = []
    for name, agg in sorted(by_name.items(), key=lambda x: x[1]["norm_cost"], reverse=True):
        result.append(ToolEconomicsRow(
            name=name,
            calls=agg["calls"],
            input_tokens=agg["input_tokens"],
            result_tokens=agg["result_tokens"],
            cache_read_tokens=agg["cache_read"],
            norm_cost=agg["norm_cost"],
        ))

    return result
```

**Note on imports**: `classify_model` and `HAIKU_BASE_UNIT` are already in `analysis.py`. The import line becomes:
```python
from cc_dump.analysis import ToolInvocation, ToolEconomicsRow, classify_model, HAIKU_BASE_UNIT
```

---

## Update render_economics_panel()

### File: `src/cc_dump/tui/panel_renderers.py`
**Lines 37-56**: Replace entire `render_economics_panel()` function:

```python
def render_economics_panel(rows: list) -> str:
    """Render the tool economics panel display text.

    Args:
        rows: List of ToolEconomicsRow from get_tool_economics()
    """
    if not rows:
        return "Tool Economics: (no tool calls yet)"

    lines = []
    lines.append("Tool Economics (session total):")
    lines.append("  {:<12} {:>5}  {:>14}  {:>8}  {:>10}".format(
        "Tool", "Calls", "Input (Cached)", "Output", "Norm Cost"
    ))
    for row in rows:
        # Format input with cache percentage
        if row.input_tokens > 0:
            total_input = row.input_tokens + row.cache_read_tokens
            if row.cache_read_tokens > 0 and total_input > 0:
                cache_pct = 100 * row.cache_read_tokens / total_input
                input_str = "{} ({:.0f}%)".format(_fmt_tokens(row.input_tokens), cache_pct)
            else:
                input_str = _fmt_tokens(row.input_tokens)
        else:
            input_str = "--"

        output_str = _fmt_tokens(row.result_tokens) if row.result_tokens > 0 else "--"
        cost_str = "{:,.0f}".format(row.norm_cost) if row.norm_cost > 0 else "--"

        lines.append("  {:<12} {:>5}  {:>14}  {:>8}  {:>10}".format(
            row.name[:12],
            row.calls,
            input_str,
            output_str,
            cost_str,
        ))

    return "\n".join(lines)
```

**Note**: The `import cc_dump.analysis` at top of file already exists (line 8). The function receives `ToolEconomicsRow` objects but uses duck-typed attribute access, so no additional import is needed.

---

## Update ToolEconomicsPanel

### File: `src/cc_dump/tui/widget_factory.py`
**Lines 1027-1049**: Update `ToolEconomicsPanel.refresh_from_db()`:

```python
def refresh_from_db(self, db_path: str, session_id: str):
    """Refresh panel data from database."""
    if not db_path or not session_id:
        self._refresh_display([])
        return

    # Query tool economics with real tokens and cache attribution
    rows = cc_dump.db_queries.get_tool_economics(db_path, session_id)
    self._refresh_display(rows)
```

**Lines 1046-1049**: Update `_refresh_display()` signature:
```python
def _refresh_display(self, rows):
    """Rebuild the economics table."""
    text = cc_dump.tui.panel_renderers.render_economics_panel(rows)
    self.update(text)
```

This removes the intermediate `aggregate_tools()` call -- the query layer now does aggregation.

---

## Adjacent Code Patterns

**Query pattern** (from `get_model_economics()`, db_queries.py lines 112-148):
```python
uri = f"file:{db_path}?mode=ro"
conn = sqlite3.connect(uri, uri=True)
try:
    cursor = conn.execute("""...""", (session_id,))
    results = []
    for row in cursor:
        results.append({...})
    return results
finally:
    conn.close()
```

**Panel renderer pattern** (from `render_timeline_panel()`, panel_renderers.py lines 59-94):
```python
lines = []
lines.append("Header:")
lines.append("  {:>4}  {:>7}  ...".format("Col1", "Col2"))
for item in data:
    lines.append("  {:>4}  {:>7}  ...".format(item.x, item.y))
return "\n".join(lines)
```

**Widget refresh pattern** (from `TimelinePanel.refresh_from_db()`, widget_factory.py lines 1069-1100):
```python
def refresh_from_db(self, db_path, session_id):
    if not db_path or not session_id:
        self._refresh_display([])
        return
    data = cc_dump.db_queries.get_query(db_path, session_id)
    self._refresh_display(data)
```
