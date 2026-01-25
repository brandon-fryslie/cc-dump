# Sprint: verification - Hot-Reload Verification and Testing
Generated: 2026-01-24
Confidence: HIGH: 2, MEDIUM: 1, LOW: 0
Status: PARTIALLY READY

## Sprint Goal
Ensure hot-reload guarantees are verified automatically, catching regressions before they break the running proxy.

## Scope
**Deliverables:**
- Test suite for hot-reload functionality
- CI-friendly verification that catches common mistakes
- Runtime validation for protocol compliance

## Work Items

### P0: Create Hot-Reload Test Suite
**Confidence: HIGH**

Comprehensive tests for the hot-reload system.

**Acceptance Criteria:**
- [ ] Test that all discovered modules can be reloaded without error
- [ ] Test that import validation catches `from module import X` violations
- [ ] Test that widget protocol is implemented by all widgets
- [ ] Test that dependency order is deterministic
- [ ] Tests run in <5 seconds

**Technical Notes:**
- Use pytest fixtures for setup/teardown
- Don't actually modify files in tests (mock mtime changes)
- Can test the actual reload mechanism on isolated modules

**Test Cases:**
```python
def test_all_modules_reloadable():
    """Every discovered module can be reloaded without exception."""

def test_import_validation_catches_violations():
    """Import checker finds 'from cc_dump.X import Y' in stable modules."""

def test_widgets_implement_protocol():
    """All widget classes have get_state and restore_state methods."""

def test_dependency_order_stable():
    """Same input always produces same reload order."""

def test_reload_preserves_state():
    """Widget state survives a reload cycle."""
```

### P1: Add Protocol Compliance Check
**Confidence: HIGH**

Runtime check that widgets satisfy the protocol.

**Acceptance Criteria:**
- [ ] Function to validate a widget implements HotSwappableWidget
- [ ] Clear error message if method missing
- [ ] Optional: validate state dict has expected keys
- [ ] Can be called in factory functions or tests

**Technical Notes:**
- Use `hasattr()` and `callable()` for duck typing check
- Or use `isinstance()` with Protocol if type checker supports it
- Don't over-validate state dict structure (too brittle)

### P2: Add Reload Smoke Test
**Confidence: MEDIUM**

End-to-end test that exercises the full reload cycle.

**Acceptance Criteria:**
- [ ] Starts a mock app with widgets
- [ ] Simulates file change detection
- [ ] Triggers reload
- [ ] Verifies widgets are replaced with state preserved
- [ ] Verifies new event handlers are used

**Technical Notes:**
- May need to mock Textual components
- Or use a minimal test harness without full TUI
- Focus on state preservation, not visual correctness

#### Unknowns to Resolve
- Can we test Textual widget replacement without running full TUI?
- How to simulate file change without actually touching filesystem?

#### Exit Criteria
- Test passes in CI environment
- Test runs in <10 seconds

## Dependencies
- Sprint 1 (protocol-definition) - Protocols must exist
- Sprint 2 (auto-registration) - For testing discovery

## Risks
- **Test flakiness**: Hot-reload involves timing, may be flaky
- **Mocking complexity**: Textual mocking may be non-trivial
- **CI environment**: May behave differently than local

## Mitigations
- Use deterministic mocks for file changes
- Test reload logic separate from Textual integration
- Skip TUI integration tests in CI if problematic
