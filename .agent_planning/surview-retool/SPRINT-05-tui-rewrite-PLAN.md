# Sprint 5: tui-rewrite - Rendering, Event Handlers, App, Widgets
Generated: 2026-02-06
Confidence: HIGH: 3, MEDIUM: 2, LOW: 0
Status: PARTIALLY READY

## Sprint Goal
Rewrite the TUI layer to consume generic HTTP blocks from Sprint 4. Remove LLM panels, add new renderers, simplify filters. After this sprint, the app should start and display HTTP traffic.

## Scope
**Deliverables:**
- New renderers for generic HTTP block types
- Simplified event handlers for new event schema
- App bindings updated (h/b/s/f)
- Economics and timeline panels removed
- Stats panel rewritten for generic HTTP metrics
- Widget factory cleaned up

## Work Items

### P0: New renderers in rendering.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] _render_request_header() — displays "GET /api/users" with request number and timestamp
- [ ] _render_response_status() — displays "HTTP 200 OK | application/json | 1.2KB | 45ms"
- [ ] _render_json_body() — syntax-highlighted JSON with indentation
- [ ] _render_text_body() — raw text display
- [ ] _render_binary_body() — "[binary: image/png, 45.2KB]" placeholder
- [ ] _render_sse_event() — "event: message | data: {preview...} (1.2KB)"
- [ ] _render_sse_stream_summary() — "[SSE: 42 events, 15.3KB, 2.1s]"
- [ ] BLOCK_RENDERERS registry updated (remove LLM entries, add new)
- [ ] BLOCK_FILTER_KEY updated for new block types
- [ ] LLM renderers deleted: _render_metadata, _render_turn_budget_block, _render_system_label, _render_tracked_content_block, _render_tool_use, _render_tool_result, _render_stream_info, _render_stream_tool_use, _render_stop_reason
- [ ] _make_tool_use_summary deleted
- [ ] render_blocks() tool-use collapse logic deleted

**Technical Notes:**
- Use Rich's built-in JSON highlighting for JsonBodyBlock if possible
- Color status codes: 2xx green, 3xx blue, 4xx yellow, 5xx red
- SSE events shown individually when sse filter is on, summary when off (similar to current tool collapse logic)

### P1: Rewrite event_handlers.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] handle_request() accepts new event shape: ("request", method, url, headers, body_bytes)
- [ ] handle_response_start() accepts: ("response_start", status_code, headers)
- [ ] handle_response_body() accepts: ("response_body", body_bytes, content_type)
- [ ] handle_sse_event() accepts: ("sse_event", event_type, data_str)
- [ ] handle_response_done() accepts: ("response_done", duration_ms)
- [ ] handle_error() and handle_proxy_error() preserved (same shape)
- [ ] All token/model tracking deleted
- [ ] economics/timeline refresh callbacks removed

**Technical Notes:**
- handle_request: call surview.formatting.format_request(), add turn to conv
- handle_response_start: format headers, begin streaming turn
- handle_sse_event: format SSE event, append to streaming turn
- handle_response_body: format body, add as non-streaming turn
- handle_response_done: finalize streaming turn, update stats

### P2: Rewrite app.py bindings and panels
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Bindings simplified: h(eaders), b(ody), s(se), f(ollow), ctrl+l(logs), a(stats)
- [ ] Remove: t(ools), e(xpand/context), m(etadata), c(cost), l(timeline), ctrl+m(breakdown)
- [ ] Remove show_tools, show_system, show_expand, show_economics, show_timeline reactives
- [ ] Add show_body, show_sse reactives
- [ ] Remove _get_economics(), _get_timeline(), _refresh_economics(), _refresh_timeline()
- [ ] Remove ToolEconomicsPanel and TimelinePanel from compose()
- [ ] active_filters returns {headers, body, sse, stats}
- [ ] _handle_event_inner() routes new event types
- [ ] _process_replay_data() updated for generic HAR data
- [ ] Log messages say "surview" not "cc-dump"

### P3: Rewrite widget_factory.py widgets
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] ToolEconomicsPanel class DELETED
- [ ] TimelinePanel class DELETED
- [ ] create_economics_panel(), create_timeline_panel() DELETED
- [ ] StatsPanel rewritten: shows request count, total bytes transferred, average response time, status code distribution
- [ ] ConversationView.next_tool_turn() deleted (no tool concept)
- [ ] FilterStatusBar updated for new filter names

#### Unknowns to Resolve
- What stats to show in the stats panel? **Proposed: requests, bytes in/out, avg latency, status code counts (2xx/3xx/4xx/5xx)**

#### Exit Criteria
- Stats panel displays generic HTTP metrics
- No references to ToolEconomicsPanel or TimelinePanel

### P4: Rewrite panel_renderers.py
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] render_economics_panel() DELETED
- [ ] render_timeline_panel() DELETED
- [ ] render_stats_panel() rewritten: displays request count, bytes, latency, status codes
- [ ] No imports from analysis.py

#### Unknowns to Resolve
- Format for bytes display? **Decision: human-readable (1.2KB, 3.4MB)**

#### Exit Criteria
- Stats panel renders generic HTTP statistics

## Dependencies
- Sprint 3 (event schema)
- Sprint 4 (formatting IR — block types and format functions)

## Risks
- **Integration complexity**: This sprint touches rendering.py + event_handlers.py + app.py + widget_factory.py + panel_renderers.py simultaneously. Must be done as a unit because they're tightly coupled via block types.
- **SSE collapse logic**: Analogous to current tool collapse — when sse filter is off, show SSEStreamSummaryBlock instead of individual SSEEventBlocks. Implementation similar to existing _make_tool_use_summary pattern.
