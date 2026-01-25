# Definition of Done: unit-tests

## Verification Checklist

### analysis.py Tests
1. [ ] `test_estimate_tokens_empty` - Empty string returns 1 (min)
2. [ ] `test_estimate_tokens_short` - "hello" → ~1-2 tokens
3. [ ] `test_estimate_tokens_long` - 1000 chars → ~250 tokens
4. [ ] `test_compute_turn_budget_minimal` - Empty request works
5. [ ] `test_compute_turn_budget_with_system` - System prompt counted
6. [ ] `test_compute_turn_budget_with_tools` - Tool defs counted
7. [ ] `test_compute_turn_budget_with_messages` - User/assistant text counted
8. [ ] `test_turn_budget_cache_hit_ratio` - Property calculations correct
9. [ ] `test_correlate_tools_matched` - tool_use matched to tool_result
10. [ ] `test_correlate_tools_unmatched` - Orphan use/result handled
11. [ ] `test_aggregate_tools_sorting` - Sorted by total_tokens_est desc

### formatting.py Tests
12. [ ] `test_format_request_minimal` - Returns expected blocks
13. [ ] `test_format_request_with_system` - System prompt blocks included
14. [ ] `test_format_request_with_messages` - Message blocks included
15. [ ] `test_format_response_event_message_start` - StreamInfoBlock created
16. [ ] `test_format_response_event_content_delta` - TextDeltaBlock created
17. [ ] `test_track_content_new` - First occurrence tagged "new"
18. [ ] `test_track_content_ref` - Second occurrence tagged "ref"
19. [ ] `test_track_content_changed` - Modified content tagged "changed"
20. [ ] `test_make_diff_lines_no_change` - Empty diff for identical content
21. [ ] `test_make_diff_lines_with_changes` - Proper diff output

### router.py Tests
22. [ ] `test_queue_subscriber_receives_events` - Events queued
23. [ ] `test_direct_subscriber_calls_function` - Function invoked
24. [ ] `test_router_fanout` - All subscribers receive event
25. [ ] `test_router_error_isolation` - Failing subscriber doesn't break others
26. [ ] `test_router_start_stop` - Clean lifecycle

## Pass Criteria

- [ ] All 25+ tests pass
- [ ] `uv run pytest tests/test_analysis.py tests/test_formatting.py tests/test_router.py -v` succeeds
- [ ] Tests run in <5 seconds total
- [ ] No mocking of external services (all pure unit tests)
