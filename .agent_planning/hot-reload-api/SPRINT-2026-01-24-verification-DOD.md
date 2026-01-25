# Definition of Done: verification

## Completion Criteria

### Test Suite
- [ ] `tests/test_hot_reload.py` exists with all test cases
- [ ] All tests pass locally
- [ ] Tests run in <5 seconds total
- [ ] No external dependencies (network, real files)

### Protocol Compliance
- [ ] `validate_widget_protocol()` function exists
- [ ] Called in test suite
- [ ] Clear error messages for violations
- [ ] All 4 widgets pass validation

### Reload Smoke Test (if MEDIUM resolved)
- [ ] End-to-end test exercises full reload
- [ ] State preservation verified
- [ ] Test is not flaky (passes 10/10 runs)

## Verification Commands
```bash
# Run all hot-reload tests
python -m pytest tests/test_hot_reload.py -v

# Run with timing
python -m pytest tests/test_hot_reload.py -v --durations=5

# Verify no flakiness
for i in {1..10}; do python -m pytest tests/test_hot_reload.py -q || echo "FAILED on run $i"; done
```

## Test Coverage Checklist
- [ ] Module discovery finds all expected modules
- [ ] Module discovery excludes stable boundaries
- [ ] Dependency graph correct for known modules
- [ ] Topological sort handles no-dependency modules
- [ ] Topological sort handles circular deps (graceful)
- [ ] Import validation catches violations
- [ ] Import validation passes clean code
- [ ] Widget protocol check passes valid widgets
- [ ] Widget protocol check fails invalid widgets
- [ ] Reload cycle preserves widget state

## Not In Scope
- Visual regression testing
- Performance benchmarking
- Load testing under high event volume
