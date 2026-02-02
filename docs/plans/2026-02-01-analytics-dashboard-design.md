# Analytics Dashboard Design

**Date**: 2026-02-01
**Status**: Approved for implementation

## Problem

Current panels (Stats, Cost, Timeline) show basic token metrics but lack critical breakdowns:
- No cached vs fresh token visibility
- No subagent categorization
- No content type breakdown (system prompts, tools, conversation)
- No input/output split
- Limited time-based analysis

Users need comprehensive token usage analysis to optimize Claude Code usage and understand costs.

## Solution

Replace three separate panels with a unified Analytics dashboard showing all token breakdowns in a single, structured view.

## Dashboard Layout

### Header: Session Summary
```
Total: 150K tokens ($1.20) | 73% cached | Input: 80K | Output: 70K
```
Compact one-liner showing the most critical metrics at a glance.

### Section 1: Cache Efficiency (Prominent)
```
Cache Hit Rate: 73%
  Cached: 109K tokens ($0.30)
  Fresh:   41K tokens ($1.05)
  Savings: $0.75 from caching
```
Shows cache performance - the most important cost optimization metric.

### Section 2: Breakdowns (Tabbed Views)

**Tab 1: By Subagent**
```
Subagent         Input    Output   Cached   Fresh    Cost
─────────────────────────────────────────────────────────
(direct)         40K      35K      50K      25K     $0.60
Explore          25K      20K      30K      15K     $0.35
Plan             10K       8K      15K       3K     $0.15
Bash              5K       7K       8K       4K     $0.10
─────────────────────────────────────────────────────────
Total            80K      70K     109K      41K     $1.20
```

**Tab 2: By Content Type**
```
Content Type     Input    Output   Cached   Fresh    Cost
─────────────────────────────────────────────────────────
System Prompts   35K       0K      30K       5K     $0.25
Tool Results     30K       0K      25K       5K     $0.20
Conversation     10K      50K      40K      20K     $0.55
Code/Text         5K      20K      14K      11K     $0.20
─────────────────────────────────────────────────────────
Total            80K      70K     109K      41K     $1.20
```

**Tab 3: By Tool**
```
Tool             Calls   Input    Output   Cached   Cost
───────────────────────────────────────────────────────
Read              15     20K       8K      18K     $0.25
Grep              10     15K       5K      12K     $0.18
Edit               8     12K      10K       8K     $0.20
Write              5     10K       8K       6K     $0.16
Task               3     23K      39K      30K     $0.41
───────────────────────────────────────────────────────
Total             41     80K      70K     109K     $1.20
```

### Section 3: Timeline (Compact)
```
Token Usage (last 20 turns)
▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▂▃▄▅▆  [Current]
```
Sparkline or mini bar chart showing recent usage trends.

## Data Flow

### Data Sources
1. **SQLite Database** - Primary source of truth for historical data
   - `turns` table: per-turn token counts
   - `tools` table: per-tool usage
   - New: Extract subagent info from tool use blocks (Task tool with subagent_type)

2. **Live Event Stream** - Real-time updates during session
   - Request/response events with token counts
   - Tool use events with metadata

### Aggregation Strategy
- Query SQLite for session totals and breakdowns
- Group by dimensions (subagent, content type, tool)
- Calculate cache efficiency from `cache_creation_input_tokens` and `cache_read_input_tokens`
- Compute input/output split from request/response pairs

### Refresh Triggers
- After each API response (update session summary, add to timeline)
- On tab switch (lazy-load breakdown data)
- On panel toggle (full refresh when dashboard becomes visible)

## Implementation Details

### New Module: `tui/analytics_panel.py`
```python
class AnalyticsPanel(ScrollableContainer):
    """Unified analytics dashboard showing comprehensive token breakdowns."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.active_tab = "subagent"  # subagent | content | tool

    def compose(self) -> ComposeResult:
        yield Static(id="session-summary")
        yield Static(id="cache-efficiency")
        yield TabbedContent(
            TabPane("By Subagent", id="tab-subagent"),
            TabPane("By Content", id="tab-content"),
            TabPane("By Tool", id="tab-tool"),
        )
        yield Static(id="timeline-sparkline")

    def on_mount(self):
        self.set_interval(2.0, self.refresh_data)

    def refresh_data(self):
        """Query SQLite and update all sections."""
        # Query database for aggregated stats
        # Update session summary
        # Update cache efficiency
        # Update active tab data
        # Update timeline
```

### Database Schema Extensions

**No schema changes needed** - existing tables have the data:
- `turns.input_tokens`, `turns.output_tokens` for input/output split
- `turns.cache_creation_input_tokens`, `turns.cache_read_input_tokens` for cache metrics
- Tool use blocks contain `subagent_type` parameter for subagent categorization
- Content type inferred from block types (system, tool_use, tool_result, text)

### Queries

**Session Summary**:
```sql
SELECT
    SUM(input_tokens) as total_input,
    SUM(output_tokens) as total_output,
    SUM(cache_read_input_tokens) as cached,
    SUM(input_tokens - cache_read_input_tokens) as fresh
FROM turns
WHERE session_id = ?
```

**By Subagent** (requires parsing tool use blocks):
```sql
-- Extract subagent_type from tool use blocks where tool_name = 'Task'
-- Group token usage by subagent_type
-- "(direct)" for turns without Task tool usage
```

**By Content Type** (requires analyzing block types in turn data):
```sql
-- Analyze block composition per turn
-- System blocks -> system prompts
-- Tool use/result blocks -> tools
-- Text blocks -> conversation
```

**By Tool**:
```sql
SELECT
    tool_name,
    COUNT(*) as calls,
    SUM(input_tokens) as input,
    SUM(output_tokens) as output,
    SUM(cache_read_input_tokens) as cached
FROM tools
WHERE session_id = ?
GROUP BY tool_name
ORDER BY input + output DESC
```

## UI/UX Details

### Keybinding
- **d** - Toggle Analytics Dashboard (replaces 'a' for stats, 'c' for cost, 'l' for timeline)
- **Tab** / **Shift+Tab** - Switch between breakdown tabs when dashboard is focused

### Tab Navigation
Tabs should be keyboard-navigable and show current selection clearly.

### Responsive Layout
- Minimum width: 60 columns (for table formatting)
- Scrollable vertically if content exceeds viewport
- Tables auto-format based on available width

### Progressive Disclosure
- Session summary always visible at top
- Cache efficiency prominent (this is the money metric)
- Tabs allow drilling into specific breakdowns without overwhelming
- Timeline compact (sparkline, not full graph)

## Migration Strategy

### Phase 1: Implement dashboard alongside existing panels
- Add new `d` keybinding for dashboard
- Keep `a`, `c`, `l` for existing panels initially
- Users can opt-in to new dashboard

### Phase 2: Gather feedback and iterate
- Validate that dashboard answers user questions
- Refine layout, add missing metrics if needed

### Phase 3: Deprecate old panels (if dashboard is successful)
- Remove `a`, `c`, `l` keybindings
- Remove Stats, Cost, Timeline panels
- Dashboard becomes the only analytics view

## Open Questions

1. **Session scope**: Should dashboard show current session only, or allow switching between sessions?
   - **Decision**: Current session only (match existing panel behavior)

2. **Historical comparison**: Should we show session-over-session trends?
   - **Decision**: Not in v1 - keep focused on current session analysis

3. **Export**: Should dashboard data be exportable?
   - **Decision**: Not in v1 - focus on live analysis first

## Success Criteria

- Users can answer: "Is caching working effectively?"
- Users can answer: "Which subagents are expensive?"
- Users can answer: "Where are my tokens going?" (content type breakdown)
- Users can answer: "Which tools cost the most?"
- Dashboard loads and updates within 200ms (no performance degradation)
- All existing panel functionality preserved or improved

## Non-Goals

- Real-time alerting (out of scope)
- Multi-session comparison (future enhancement)
- Export/reporting (future enhancement)
- Predictive analysis (future enhancement)
