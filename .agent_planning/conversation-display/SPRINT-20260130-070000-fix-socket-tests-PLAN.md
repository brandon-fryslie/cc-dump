# Sprint: fix-socket-tests - Fix Integration Test Socket Failures
Generated: 2026-01-30T07:00:00
Confidence: HIGH: 1, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Fix 11 integration tests in test_tui_integration.py that fail due to pytest-socket (a globally-installed pytest plugin) blocking socket creation.

## Root Cause Analysis
- `pytest-socket` (v0.7.0) is installed globally via `pytest-homeassistant-custom-component` (another project's dependency)
- It auto-registers as a pytest plugin and blocks ALL socket creation by default
- 11 integration tests use `requests.post()` to send HTTP to localhost, which requires socket creation
- This is NOT a project dependency — it's environmental pollution from another project sharing the same Python environment

## Scope
**Deliverables:**
- Fix all 11 failing integration tests to work with pytest-socket active

## Work Items

### P0 - Allow sockets for integration tests that need network access
**Confidence**: HIGH
**Dependencies**: None

#### Options Considered

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| A (Recommended) | Add `@pytest.mark.enable_socket` to the 11 tests | Minimal change, explicit, surgical | Must add to each new test that needs sockets |
| B | Add `--allow-hosts=127.0.0.1` to pyproject.toml addopts | Global fix, no per-test markers | Weakens socket blocking for ALL tests; project doesn't use pyproject.toml for pytest config yet |
| C | Disable pytest-socket entirely via `addopts = -p no:pytest_socket` | Removes the problem entirely | Loses the safety net for future tests; heavy-handed |
| D | Add `conftest.py` fixture that enables sockets for the integration test file | One fixture, all tests in file get sockets | Implicit — harder to see which tests need network |

**Recommendation**: Option A — `@pytest.mark.enable_socket` on each test that uses `requests.post()`. This is explicit, minimal, and self-documenting. Each test that needs network access declares it.

#### Acceptance Criteria
- [ ] All 11 failing tests pass with `@pytest.mark.enable_socket` marker
- [ ] No changes to tests that don't need network access
- [ ] Full test suite passes (55 widget/scroll-nav + 52 previously-passing integration tests + 11 fixed tests)

#### Technical Notes
The 11 tests that need the marker:
1. `TestRequestHandling::test_displays_request_when_received`
2. `TestRequestHandling::test_handles_multiple_requests`
3. `TestVisualIndicators::test_content_shows_filter_indicators`
4. `TestContentFiltering::test_headers_filter_controls_request_headers`
5. `TestContentFiltering::test_metadata_filter_controls_model_info`
6. `TestStatsPanel::test_stats_panel_updates_on_request`
7. `TestErrorHandling::test_tui_survives_malformed_request`
8. `TestRenderingStability::test_tui_handles_large_content`
9. `TestConversationView::test_conversation_view_displays_messages`
10. `TestConversationView::test_conversation_view_handles_streaming`
11. `TestIntegrationScenarios::test_complete_filter_workflow`

All use `requests.post()` to `http://127.0.0.1:{port}/v1/messages`.

## Dependencies
- None (standalone fix)

## Risks
- LOW: If pytest-socket is ever removed from the environment, the markers become no-ops (harmless)
