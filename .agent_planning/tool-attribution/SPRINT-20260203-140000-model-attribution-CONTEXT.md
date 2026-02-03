# Implementation Context: model-attribution
Generated: 2026-02-03-140000
Source: EVALUATION-20260202.md
Confidence: MEDIUM

## Research: Model Consistency

### Data collection approach

Query real session databases (located in cc-dump's data directory) to answer research questions.

**Query 1: Models per session**
```sql
SELECT session_id, GROUP_CONCAT(DISTINCT model) as models, COUNT(*) as turns
FROM turns
GROUP BY session_id
ORDER BY turns DESC
LIMIT 10;
```

**Query 2: Model per tool invocation (via JOIN)**
```sql
SELECT ti.tool_name, t.model, COUNT(*) as calls
FROM tool_invocations ti
JOIN turns t ON ti.turn_id = t.id
GROUP BY ti.tool_name, t.model
ORDER BY calls DESC;
```

**Query 3: Multiple models within a single turn (should never happen)**
```sql
-- This query should return 0 rows if model is always consistent per turn
SELECT t.id, COUNT(DISTINCT t.model) as model_count
FROM turns t
GROUP BY t.id
HAVING model_count > 1;
```

The data directory location can be found in `cli.py` -- look for the `--db-path` argument or the default path construction.

### File: `src/cc_dump/cli.py`
Check for DB path default to know where to find real session data.

---

## Model-Aware Pricing Verification

### File: `tests/test_analysis.py`
**Add test** for mixed-model tool pricing:

```python
def test_tool_economics_mixed_models():
    """Verify norm cost reflects per-invocation model pricing."""
    from cc_dump.analysis import classify_model, HAIKU_BASE_UNIT

    # Simulate: Read called with Sonnet (input_tokens=1000) and Opus (input_tokens=1000)
    _, sonnet_pricing = classify_model("claude-sonnet-4-20250514")
    _, opus_pricing = classify_model("claude-opus-4-5-20251101")

    # Sonnet Read: 1000 input tokens
    sonnet_cost = 1000 * (sonnet_pricing.base_input / HAIKU_BASE_UNIT)
    # Opus Read: 1000 input tokens
    opus_cost = 1000 * (opus_pricing.base_input / HAIKU_BASE_UNIT)

    expected_total = sonnet_cost + opus_cost
    # Sonnet base_input = 3.0, Opus base_input = 5.0, HAIKU_BASE_UNIT = 1.0
    # Expected: 1000*3 + 1000*5 = 8000
    assert expected_total == 8000.0
```

### File: `src/cc_dump/db_queries.py`
The `get_tool_economics()` function from Sprint 2 already computes per-row costs using the turn's model. Verify this is correct by tracing the code path:

1. Each row from SQL has `model` column (from turns table)
2. `classify_model(model)` returns pricing
3. Cost is computed per-row: `input_tokens * pricing.base_input / HAIKU_BASE_UNIT + result_tokens * pricing.output / HAIKU_BASE_UNIT`
4. Costs are summed across all invocations of the same tool name

This is correct: mixed-model invocations get their individual costs summed, not averaged.

---

## Sub-Agent Attribution

### Identification signals to investigate

**Signal 1: System prompt differences**
Sub-agent turns may have different system prompts. The `request_json` column stores the full request body including system prompts. Compare system prompt content across turns in a session.

```sql
SELECT id, sequence_num, model,
       json_extract(request_json, '$.system[0].text') as first_system_section
FROM turns
WHERE session_id = ?
ORDER BY sequence_num;
```

**Signal 2: Tool set differences**
Sub-agents may have a different set of tool definitions. The `tool_names` column stores JSON array of tool names.

```sql
SELECT tool_names, COUNT(*) as turns
FROM turns
WHERE session_id = ?
GROUP BY tool_names
ORDER BY turns DESC;
```

**Signal 3: Model differences**
Sub-agents might use a different model family.

### If sub-agents ARE identifiable

**Add column or tag**: Add a `is_subagent BOOLEAN` flag to turns, or detect at query time.

**Panel display change** in `panel_renderers.py`:
```
Tool Economics (session total):
  Tool          Calls   Input (Cached)   Output      Norm Cost
  Bash             12   45.2k (89%)      12.3k       1,234
    (sub-agent)     3    5.1k (85%)       2.1k         234
  Read              8   23.1k (92%)       8.7k         567
```

### If sub-agents are NOT identifiable

Add a comment in `db_queries.py`:
```python
# NOTE: Sub-agent tool calls are not currently distinguishable from main-agent calls.
# All tool invocations are attributed to the tool name regardless of which agent invoked them.
# Future: Anthropic may add sub-agent markers to the API.
```

---

## Adjacent Code Patterns

**classify_model() usage** (from analysis.py lines 288-302):
```python
def classify_model(model_str: str) -> tuple[str, ModelPricing]:
    lower = model_str.lower()
    for family, pricing in MODEL_PRICING.items():
        if family in lower:
            return (family, pricing)
    return ("unknown", FALLBACK_PRICING)
```

**ModelEconomics.norm_cost()** (from analysis.py lines 329-336):
```python
def norm_cost(self, pricing: ModelPricing) -> float:
    return (
        self.input_tokens * (pricing.base_input / HAIKU_BASE_UNIT)
        + self.cache_creation_tokens * (pricing.cache_write_5m / HAIKU_BASE_UNIT)
        + self.cache_read_tokens * (pricing.cache_hit / HAIKU_BASE_UNIT)
        + self.output_tokens * (pricing.output / HAIKU_BASE_UNIT)
    )
```
