# Sprint: unit-tests - Add Unit Tests for Core Modules
Generated: 2026-01-24
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Add comprehensive unit tests for analysis.py, formatting.py, and router.py to enable safe refactoring and catch regressions.

## Scope
**Deliverables:**
- Unit tests for analysis.py (token estimation, turn budget, tool correlation)
- Unit tests for formatting.py (block generation, content tracking, diff logic)
- Unit tests for router.py (event distribution, subscriber error isolation)

## Work Items

### P0: Unit tests for analysis.py (~16 tests)
**Confidence: HIGH**

**Functions to Test:**
1. `estimate_tokens(text)` - Token estimation heuristic
2. `compute_turn_budget(request_body)` - Budget breakdown computation
3. `correlate_tools(messages)` - Tool use/result matching
4. `aggregate_tools(invocations)` - Per-tool aggregation
5. `tool_result_breakdown(messages)` - Per-tool token breakdown

**Acceptance Criteria:**
- [ ] `estimate_tokens()`: Empty string, short text, long text, unicode
- [ ] `compute_turn_budget()`: Simple request, with tools, with messages, nested content blocks
- [ ] `TurnBudget` properties: cache_hit_ratio edge cases (0/0, 100%, 50%)
- [ ] `correlate_tools()`: No tools, matched pair, unmatched use/result, error flag
- [ ] `aggregate_tools()`: Empty list, single tool, multiple tools, sorting by total
- [ ] `tool_result_breakdown()`: Integration of correlate + breakdown

**Technical Notes:**
- Pure functions with no I/O - easy to test
- Use pytest fixtures for sample request bodies
- Test edge cases: empty inputs, missing fields, malformed data

### P1: Unit tests for formatting.py (~20 tests)
**Confidence: HIGH**

**Functions to Test:**
1. `format_request(body, state)` - Request → block list
2. `format_response_event(event_type, data)` - Response event → block list
3. `track_content(content, position_key, state)` - Content dedup/tracking
4. `make_diff_lines(old, new)` - Unified diff generation

**Acceptance Criteria:**
- [ ] `format_request()`: Minimal request, with system prompt, with messages, with tools
- [ ] `format_response_event()`: Each event type (message_start, content_block_delta, message_delta, message_stop)
- [ ] `track_content()`: First seen (new), second seen (ref), changed content (changed with diff)
- [ ] `make_diff_lines()`: No change, single line change, multi-line change, additions, deletions
- [ ] Block dataclasses: All 19 block types can be instantiated with expected fields

**Technical Notes:**
- State dict is mutable - test state changes across calls
- Content tracking uses hashes - test hash collision handling
- Use snapshot testing for complex block structures if beneficial

### P2: Unit tests for router.py (~6 tests)
**Confidence: HIGH**

**Components to Test:**
1. `QueueSubscriber` - Puts events into queue
2. `DirectSubscriber` - Calls function inline
3. `EventRouter` - Fan-out, error isolation, start/stop

**Acceptance Criteria:**
- [ ] `QueueSubscriber`: Events added to queue, order preserved
- [ ] `DirectSubscriber`: Function called with event
- [ ] `EventRouter.add_subscriber()`: Subscribers receive events
- [ ] `EventRouter`: Multiple subscribers all receive same event
- [ ] Error isolation: One subscriber failure doesn't affect others
- [ ] Start/stop: Clean startup and graceful shutdown

**Technical Notes:**
- Router is threaded - use threading.Event for synchronization in tests
- Mock time-sensitive operations (queue timeout)
- Test error paths by using a subscriber that raises

## Dependencies
- None (foundational work)

## Risks
- **Thread timing in router tests**: Use events/conditions for synchronization
- **State mutation in formatting tests**: Reset state between tests

## Test Organization

```
tests/
├── conftest.py              # Shared fixtures
├── test_hot_reload.py       # Existing E2E tests
├── test_analysis.py         # NEW: analysis.py unit tests
├── test_formatting.py       # NEW: formatting.py unit tests
└── test_router.py           # NEW: router.py unit tests
```

## Success Metrics
- 42+ new unit tests passing
- Coverage for all public functions in target modules
- Tests run in <5 seconds (fast feedback)
