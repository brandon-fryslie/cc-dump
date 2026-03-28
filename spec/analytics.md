# Analytics

## Overview

### Why analytics exists

Claude Code does not surface token usage, caching behavior, or cost data to users in any
meaningful way. A single conversation can consume hundreds of thousands of tokens across
dozens of API turns, with cache hit rates and model choices silently determining cost. Without
visibility into these aggregates, users cannot answer basic questions: How much is this
session costing me? Is caching working? Which tools are consuming the most tokens? How fast
is my context window filling up?

The analytics system exists to answer these questions in real time. It accumulates per-turn
token counts, tool invocations, and model metadata from the event stream, then projects
that data into dashboard panels the user can cycle through without leaving the conversation
view.

### Design intent

Analytics is a **derived, runtime-only** layer that replaces a prior SQLite-based persistence design (the module docstring notes "Replaces SQLite persistence"). HAR files are the persistent source of truth for raw event data. The analytics store holds in-memory aggregates computed from events as they flow through the pipeline. If the process restarts, analytics state is lost (though it can be rebuilt by replaying a HAR file). This keeps the analytics path simple: no database, no migrations, no durability concerns.

The analytics panels are designed for glanceable monitoring, not deep analysis. Three
dashboard views (summary, timeline, models) cover the most common questions. Users cycle
between them with a single keypress.

---

## Data Model

### Per-Turn Record (`TurnRecord`)

Every completed API turn (one request + one response) produces a `TurnRecord` stored in
memory. This is the atomic unit of analytics data.

**Identity and ordering:**

| Field | Type | Description |
|-------|------|-------------|
| `sequence_num` | int | Monotonically increasing turn counter (1-based) |
| `request_id` | str | Unique identifier for the HTTP request |
| `session_id` | str | Claude Code session UUID extracted from `metadata.user_id` |
| `provider` | str | `"anthropic"` or other provider key (e.g. `"copilot"`) |

**Token counts (from API response `usage` field):**

| Field | Type | Description |
|-------|------|-------------|
| `input_tokens` | int | Fresh input tokens (not from cache) |
| `output_tokens` | int | Output tokens generated |
| `cache_read_tokens` | int | Input tokens served from prompt cache |
| `cache_creation_tokens` | int | Input tokens written to prompt cache |

These are **actual counts reported by the API**, not estimates. Provider-specific usage key
names are normalized at the analytics store boundary (`_normalize_usage`):
- Anthropic: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`
- OpenAI: `prompt_tokens` (mapped to `input_tokens`), `completion_tokens` (mapped to `output_tokens`). Note: the normalization uses Python `or` semantics (`usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)`), which means if `input_tokens` exists but is `0`, it will fall back to `prompt_tokens` because `0 or X` evaluates to `X` in Python. This is unlikely to matter in practice but is a code-level quirk. OpenAI responses currently have no cache-related usage fields, so `cache_read_input_tokens` and `cache_creation_input_tokens` normalize to 0 when those keys are absent.

**Model and response metadata:**

| Field | Type | Description |
|-------|------|-------------|
| `model` | str | Full model identifier (e.g., `"claude-sonnet-4-20250514"`) |
| `stop_reason` | str | Anthropic `stop_reason` or OpenAI `choices[0].finish_reason` |
| `was_interrupted` | bool | True if stop_reason is in `{"max_tokens", "length", "content_filter"}` |
| `purpose` | str | Always `"primary"` (hardcoded in `_handle_request`) |
| `prompt_version` | str | Always `""` (hardcoded in `_handle_request`; field exists but is never populated from request data) |
| `policy_version` | str | Always `""` (hardcoded in `_handle_request`; field exists but is never populated from request data) |

**Timing:**

| Field | Type | Description |
|-------|------|-------------|
| `request_recv_ns` | int | Monotonic nanosecond timestamp of request receipt (from `RequestHeadersEvent.recv_ns`, falling back to `RequestBodyEvent.recv_ns`) |
| `response_recv_ns` | int | Monotonic nanosecond timestamp of response completion (from `ResponseCompleteEvent.recv_ns`) |
| `latency_ms` | float | `max(0.0, (response_recv_ns - request_recv_ns) / 1_000_000)` |

**Retry tracking:**

| Field | Type | Description |
|-------|------|-------------|
| `retry_key` | str | SHA-1 hex digest of canonical request fields (provider, session, purpose, model, system, messages, tools, max_tokens, temperature) |
| `retry_ordinal` | int | 0 for first attempt, incremented for retries with same fingerprint |
| `transport_retry_count` | int | Value from retry headers, checked in order: `x-stainless-retry-count`, `anthropic-retry-attempt`, `x-retry-count`, `retry-count` |

**Tool invocations:**

| Field | Type | Description |
|-------|------|-------------|
| `tool_invocations` | list[ToolInvocationRecord] | Correlated tool_use/tool_result pairs |
| `command_count` | int | Number of shell commands extracted from tool inputs (both Anthropic `tool_use` content blocks and OpenAI `tool_calls` function arguments with a `command` key) |
| `command_families` | tuple[str, ...] | Sorted, deduplicated first tokens of commands (e.g., `("git", "npm")`) |

**Other:**

| Field | Type | Description |
|-------|------|-------------|
| `request_json` | str | JSON-serialized request body (retained for timeline budget calculation) |

### Tool Invocation Record (`ToolInvocationRecord`)

Each matched tool_use/tool_result pair within a turn:

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | str | Name of the tool (e.g., `"Bash"`, `"Read"`, `"Edit"`) |
| `tool_use_id` | str | Correlation ID linking use to result |
| `input_tokens` | int | **Estimated** tokens for tool input (via `count_tokens` -> `estimate_tokens`) |
| `result_tokens` | int | **Estimated** tokens for tool result (same path) |
| `is_error` | bool | Whether the tool result was marked as error |

Note: Tool-level token counts are **estimates** using the `~4 chars/token` heuristic. They
are used for relative sizing and economics, not for billing accuracy.

---

## Aggregate Computations

### Token Estimation

All estimated token counts use a single canonical function: `estimate_tokens(text)` which computes `max(1, len(text) // 4)`. This heuristic is shared across per-turn budget analysis, tool economics, and any display that shows estimated counts. The compatibility wrapper `count_tokens(text)` in `token_counter.py` delegates to `estimate_tokens` and returns 0 for empty strings. Estimated values are clearly distinct from actual API usage counts reported in response `usage` fields.

Token display uses compact formatting via `fmt_tokens(n)` with suffix notation:
- Values < 1,000: shown as-is (e.g., `"847"`)
- Values >= 1,000: `"k"` suffix (e.g., `"12.5k"`)
- Values >= 1,000,000: `"M"` suffix (e.g., `"1.2M"`)
- Values >= 1,000,000,000: `"B"` suffix

Trailing zeros and unnecessary decimal points are stripped (e.g., `"12.0k"` becomes `"12k"`).

### Model Classification

Model strings are classified into families by `classify_model(model_str)` using substring matching against a known table, matched longest-first to avoid prefix collisions (e.g., `"gpt-4o-mini"` matches before `"gpt-4o"`).

Known families and their pricing ($/MTok):

| Family | Base Input | Cache Write | Cache Hit | Output |
|--------|-----------|-------------|-----------|--------|
| opus | 5.00 | 6.25 | 0.50 | 25.00 |
| sonnet | 3.00 | 3.75 | 0.30 | 15.00 |
| haiku | 1.00 | 1.25 | 0.10 | 5.00 |
| gpt-4o | 2.50 | 2.50 | 1.25 | 10.00 |
| gpt-4o-mini | 0.15 | 0.15 | 0.075 | 0.60 |
| o1 | 15.00 | 15.00 | 7.50 | 60.00 |
| o1-mini | 3.00 | 3.00 | 1.50 | 12.00 |
| o3-mini | 1.10 | 1.10 | 0.55 | 4.40 |

Unrecognized models fall back to **sonnet pricing** (`FALLBACK_PRICING`).

Display names are derived from family via `_MODEL_FAMILY_DISPLAY`. `format_model_short` produces names like `"Opus 4.6"`, `"Sonnet 4"`, `"GPT-4o"`. Version numbers are only extracted from Anthropic model strings (`_ANTHROPIC_FAMILIES = {"opus", "sonnet", "haiku"}`) using the pattern `<family>-<major>[-<minor>]`. OpenAI model suffixes are dates, not versions, and are not shown. `format_model_ultra_short` returns the lowercase family name only (e.g., `"sonnet"`, `"opus"`, `"gpt-4o"`, `"o1"`), or `"unknown"` for unrecognized models. It handles both Anthropic and OpenAI model families.

### Cost Calculation

Session cost in USD (per model, per turn):

```
cost = (input_tokens * base_input / 1_000_000)
     + (cache_creation_tokens * cache_write / 1_000_000)
     + (cache_read_tokens * cache_hit / 1_000_000)
     + (output_tokens * output / 1_000_000)
```

Cache savings in USD (per turn, computed in `get_dashboard_snapshot`):

```
savings = cache_read_tokens * (base_input - cache_hit) / 1_000_000
```

### Context Window

Known context window sizes per family (all current Claude models: 200k, GPT-4o/4o-mini:
128k, o1: 200k, o1-mini: 128k, o3-mini: 200k). Fallback: 200k (`FALLBACK_CONTEXT_WINDOW`).

### Capacity Tracking

An optional `CC_DUMP_TOKEN_CAPACITY` environment variable sets a total token budget. When
set, the summary panel shows capacity usage as a percentage and remaining tokens. When unset,
the capacity line displays `"n/a (set CC_DUMP_TOKEN_CAPACITY)"`. Capacity fields are attached to the summary by `_with_capacity_summary()` in `event_handlers.py` after `get_dashboard_snapshot()` returns.

---

## Per-Turn Budget (Inline Display)

Separate from the aggregate analytics panels, each turn in the conversation view can display
a `TurnBudgetBlock` showing the token budget breakdown for that specific API request. This
block belongs to the `metadata` category and respects the visibility system.

The budget is computed by `compute_turn_budget(request_body)` from the request body (not the response usage). It provides **estimated** token counts broken down by category:

| Category | Description |
|----------|-------------|
| `system_tokens_est` | System prompt tokens (handles both string and content-block-list formats) |
| `tool_defs_tokens_est` | Tool definition tokens (JSON-serialized tools array) |
| `user_text_tokens_est` | User message text |
| `assistant_text_tokens_est` | Assistant message text |
| `tool_use_tokens_est` | Tool invocation inputs (Anthropic `tool_use` blocks + OpenAI `tool_calls` function arguments) |
| `tool_result_tokens_est` | Tool result contents (Anthropic `tool_result` blocks + OpenAI `role="tool"` messages) |

Additionally, **actual** token counts from the API response usage are attached:

| Field | Description |
|-------|-------------|
| `actual_input_tokens` | Fresh input tokens |
| `actual_cache_read_tokens` | Cached input tokens |
| `actual_cache_creation_tokens` | Tokens written to cache |
| `actual_output_tokens` | Output tokens |

Derived properties: `cache_hit_ratio` (`cache_read / (input + cache_read)`), `fresh_input_tokens` (alias for `actual_input_tokens`), `total_input_tokens` (`input + cache_read`), `conversation_tokens_est` (`user + assistant`).

### Cache Zone Analysis

When actual usage data is available, `compute_cache_zones(request_body, ...)` classifies each section of the request (tools, system, messages) into a cache zone based on its midpoint position in the token stream:

- **CACHE_READ** (`"cached"`): Section was served from prompt cache
- **CACHE_WRITE** (`"cache write"`): Section was added to prompt cache
- **FRESH** (`"fresh"`): Section was processed fresh

Sections are built in API wire order: tools, system, then individual messages. Zone boundaries are computed by scaling estimated section sizes proportionally to match actual usage totals (`ratio = actual_total / est_total`). Each section's midpoint (`cumulative + scaled/2`) is compared against `cache_read_end` and `cache_write_end` boundaries. This is a best-effort heuristic since the API does not report per-section cache status.

---

## Dashboard Panels

### Panel Location and Cycling

The analytics dashboard is displayed in the `StatsPanel` widget, one of two cycling panels
accessible via the `.` key (the other is the session panel). The `,` key cycles the
intra-panel view mode within the active panel.

Panel cycling order (from `PANEL_REGISTRY` in `panel_registry.py`): `session` -> `stats` -> (wraps).

### Dashboard Snapshot

All panel views render from a single canonical snapshot dict produced by
`AnalyticsStore.get_dashboard_snapshot()`. The snapshot has three keys:

```python
{
    "summary": DashboardSummary,    # Aggregate counters
    "timeline": [DashboardTimelineRow, ...],  # Per-turn timeline
    "models": [DashboardModelRow, ...],       # Per-model breakdown
}
```

The snapshot incorporates data from the **currently in-progress turn** (if streaming) by
merging partial usage data from the focused stream. Specifically, `_focused_current_turn_usage()` in `event_handlers.py` resolves the focused stream's `request_id` from `DomainStore.get_focused_stream_id()`, looks up its partial usage from `app_state["current_turn_usage_by_request"]`, and passes it as `current_turn` to `get_dashboard_snapshot()`. A pending row is included only when at least one token count is non-zero.

Capacity fields (`capacity_total`, `capacity_used`, `capacity_remaining`, `capacity_used_pct`)
are attached to the summary after snapshot generation by `_with_capacity_summary()`, derived from the `CC_DUMP_TOKEN_CAPACITY` environment variable.

Snapshot refresh is **throttled to at most once per second** during streaming deltas only (`_STATS_REFRESH_INTERVAL_NS = 1_000_000_000` in `event_handlers.py`). Turn completion and request receipt trigger an unthrottled immediate refresh via `_refresh_stats_snapshot`.

### View Mode: Summary

**Activation:** Default view (index 0), or cycle with `,` until `SUMMARY` is highlighted.

**Tab bar:** `Analytics: SUMMARY | timeline | models  (Tab/, cycle)`

**Display fields:**

```
Summary:
  Turns: <N>  Total: <total_tokens>  Cost: $<cost_usd>
  Input: <fresh> fresh + <cached> cached = <input_total>  |  Output: <output>
  Cache: <pct>% hit  |  Writes: <cache_creation>  |  Savings: $<savings>
  Models: <count> active  |  Latest: <model_label>
  Lanes(active): <main> main turns | <subagent> subagent turns | <streams> active subagent streams
  Lanes(all): <all_main> main turns | <all_subagent> subagent turns | <all_streams> active subagent streams
  Capacity: <pct>% used | <used> / <total> | remaining <remaining>
```

**Summary fields:**

| Field | Source |
|-------|--------|
| `turn_count` | Count of completed + in-progress turns |
| `input_tokens` | Sum of fresh input tokens across all turns |
| `output_tokens` | Sum of output tokens across all turns |
| `cache_read_tokens` | Sum of cache-read tokens |
| `cache_creation_tokens` | Sum of cache-write tokens |
| `input_total` | `input_tokens + cache_read_tokens` |
| `total_tokens` | `input_total + output_tokens` |
| `cache_pct` | `100 * cache_read_tokens / input_total` |
| `cost_usd` | Sum of per-model cost from model rows |
| `cache_savings_usd` | Sum of `cache_read_tokens * (base_input - cache_hit) / 1M` per turn |
| `active_model_count` | Count of distinct models (from model rows) |
| `latest_model_label` | `format_model_short()` of the last row's model |

**Lane counts** (`main_turns`, `subagent_turns`, `active_subagent_streams`, and `all_*` variants): The renderer reads these keys from the summary dict, but they are **never populated** by `AnalyticsStore.get_dashboard_snapshot()` or any post-processing step. They always default to 0. The `DashboardSummary` TypedDict does not include these keys. This is dead display code awaiting a future multi-stream/subagent tracking feature.

### View Mode: Timeline

**Activation:** Cycle with `,` until `TIMELINE` is highlighted (index 1).

**Tab bar:** `Analytics: summary | TIMELINE | models  (Tab/, cycle)`

**Display:**

```
Timeline:
  Trend In: <sparkline>
  Turn  Model        In      Out  Cache%      ΔIn
  <seq>  <model>  <input>  <output>  <pct>%  <delta>
  ...
```

Shows the last 12 turns (hardcoded `max_rows=12` default in `render_analytics_timeline`). Each row shows:

| Column | Description |
|--------|-------------|
| Turn | Sequence number |
| Model | `format_model_ultra_short()` of model string, truncated to 11 chars |
| In | `input_tokens + cache_read_tokens` for that turn |
| Out | `output_tokens` for that turn |
| Cache% | `100 * cache_read_tokens / input_total` for that turn |
| ΔIn | Difference in input_total from previous turn (`+Nk` or `-Nk`); `"--"` when delta is 0 (first turn or identical) |

**Sparkline:** Uses Unicode block characters `"▁▂▃▄▅▆▇█"` (8 glyphs). Maps input_total values to height levels via `min((value * 7) // high, 7)` where `high = max(values)`. Shows the same last-12 turns as the table. When `high <= 0`, returns the lowest glyph repeated.

### View Mode: Models

**Activation:** Cycle with `,` until `MODELS` is highlighted (index 2).

**Tab bar:** `Analytics: summary | timeline | MODELS  (Tab/, cycle)`

**Display:**

```
Models:
  Model          Turns    Input    Output  Cache%  Share       Cost
  <label>        <N>     <input>  <output>  <pct>%  <share>%  $<cost>
  ...
```

One row per distinct model, sorted by total tokens descending (ties broken by model_label ascending). Fields:

| Column | Description |
|--------|-------------|
| Model | `format_model_short()` label, truncated to 13 chars |
| Turns | Number of turns using this model |
| Input | `input_tokens + cache_read_tokens` for this model |
| Output | `output_tokens` for this model |
| Cache% | Cache hit percentage for this model's turns |
| Share | Percentage of total tokens attributed to this model |
| Cost | Cost in USD for this model's turns |

---

## Tool Economics

The analytics store provides per-tool economics data via `get_tool_economics()`, supporting
two aggregation modes:

- **By tool name** (default, `group_by_model=False`): One row per tool, aggregated across all models
- **By tool name + model** (`group_by_model=True`): One row per (tool, model) pair for breakdown analysis

Each row is a `ToolEconomicsRow` (defined in `analysis.py`) containing:

| Field | Description |
|-------|-------------|
| `name` | Tool name |
| `calls` | Invocation count |
| `input_tokens` | Estimated total input tokens (heuristic) |
| `result_tokens` | Estimated total result tokens (heuristic) |
| `cache_read_tokens` | Proportional cache attribution from parent turn |
| `norm_cost` | Normalized cost in Haiku-base-input units |
| `model` | `None` for aggregate mode, model string for breakdown mode |

**Cache attribution:** Tool-level cache read tokens are proportionally attributed from the
parent turn's `cache_read_tokens` based on each tool's share of the turn's total tool input
tokens (`proportion = inv.input_tokens / turn_tool_total`).

**Normalized cost:** Uses model pricing relative to Haiku base input rate (`HAIKU_BASE_UNIT = 1.0` $/MTok).
Formula: `input_tokens * (model_base_input / 1.0) + result_tokens * (model_output / 1.0)`.
This enables cross-model cost comparison.

Results are sorted by normalized cost descending (with name and model as tiebreakers in group-by-model mode).

**No panel consumer:** Tool economics data is available via the `get_tool_economics()` method but no panel renderer currently consumes it. No dashboard view renders this data.

---

## Data Flow

### Event-to-Aggregate Pipeline

```
proxy.py (HTTP intercept)
    |
    | emits PipelineEvents
    v
router.py (fan-out)
    |
    +---> AnalyticsStore.on_event()    <-- DirectSubscriber
    |         |
    |         | REQUEST_HEADERS -> store _RequestMeta (recv_ns, transport_retry_count)
    |         | REQUEST -> store _PendingTurn (model, session, body, pops _RequestMeta)
    |         | RESPONSE_COMPLETE -> commit TurnRecord (normalizes usage, extracts stop_reason)
    |         |
    |         v
    |     _turns: list[TurnRecord]     <-- in-memory storage
    |
    +---> TUI event handlers           <-- QueueSubscriber
              |
              | on turn completion or streaming delta:
              |   _refresh_stats_snapshot() / _refresh_stats_snapshot_throttled()
              |     |
              |     | AnalyticsStore.get_dashboard_snapshot(current_turn=focused_usage)
              |     |   -> builds summary, timeline, models dicts
              |     |
              |     | _with_capacity_summary()
              |     |   -> attaches CC_DUMP_TOKEN_CAPACITY fields
              |     |
              |     | view_store.set("panel:stats_snapshot", snapshot)
              |     |   -> triggers reactive update
              |
              v
          StatsPanel (reactive observer via snarfx)
              |
              | observes view_store["panel:stats_snapshot"]
              | renders via panel_renderers.render_analytics_panel()
              v
          Displayed text
```

### Key boundaries

1. **AnalyticsStore** is the sole writer of `TurnRecord` data. It subscribes to events
   as a `DirectSubscriber` (inline, not queued).

2. **`_refresh_stats_snapshot()`** in `event_handlers.py` is the sole writer of the
   `panel:stats_snapshot` view store key. It calls `get_dashboard_snapshot()` and
   enriches the result with capacity data.

3. **StatsPanel** is a reactive observer of `panel:stats_snapshot` via `stx.reaction`. When the view store
   value changes, it re-renders using the panel renderer for the current view mode.

4. **Panel renderers** are pure functions: `dict -> str`. They have no state, no I/O,
   and are hot-reloadable.

### Streaming updates

During streaming, `_upsert_current_turn_usage()` in `event_handlers.py` tracks in-progress turn usage in `app_state["current_turn_usage_by_request"]`, keyed by `request_id`. It merges `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, and `model` from `ResponseProgressEvent` fields. The focused stream's partial usage data is resolved by `_focused_current_turn_usage()` and merged into the dashboard snapshot so analytics update in real time, not just on turn completion.

To avoid excessive recomputation, streaming refreshes are throttled to once per second
(`_STATS_REFRESH_INTERVAL_NS = 1_000_000_000`). Turn completion and request handling call `_refresh_stats_snapshot` directly (unthrottled).

### Pruning Limits

The analytics store enforces two pruning limits on auxiliary tracking maps to prevent unbounded memory growth:
- **`_REQUEST_META_LIMIT = 2048`**: Maximum pending request metadata entries. Pruned FIFO after each `REQUEST_HEADERS` event.
- **`_RETRY_ORDINAL_LIMIT = 8192`**: Maximum retry ordinal tracking entries. Pruned FIFO after each turn commit.

### Hot-reload survival

`AnalyticsStore` implements `get_state()` / `restore_state()` for hot-reload preservation.
All `TurnRecord` data (including `tool_invocations`), pending turns, retry ordinals, request metadata, and the sequence counter are serialized and restored across reloads. The `StatsPanel` preserves its current `view_index`.

---

## Per-Turn Metrics Export

`AnalyticsStore.get_turn_metrics_snapshot()` produces a structured export of all per-turn
metrics with explicit schema versioning:

```python
{
    "schema": "cc_dump.per_turn_metrics",
    "version": 1,
    "records": [TurnMetricRecord, ...]
}
```

Each `TurnMetricRecord` includes: `sequence_num`, `request_id`, `session_id`, `provider`, `purpose`, `model`, `stop_reason`, all four token counts, `request_recv_ns`, `response_recv_ns`, `latency_ms`, `retry_key`, `retry_ordinal`, `transport_retry_count`, `is_retry` (derived: `retry_ordinal > 0`), `was_interrupted`, `tool_invocation_count`, `tool_names` (sorted unique set), `command_count`, and `command_families`.

This provides a deterministic, serializable view of analytics data suitable for external
consumption or debugging.
