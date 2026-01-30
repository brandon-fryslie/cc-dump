# Definition of Done: fix-socket-tests
Generated: 2026-01-30T07:00:00
Status: READY FOR IMPLEMENTATION (HIGH: 1)
Plan: SPRINT-20260130-070000-fix-socket-tests-PLAN.md

## Acceptance Criteria

### Fix socket-blocked integration tests
- [ ] All 11 failing tests have `@pytest.mark.enable_socket` marker
- [ ] No changes to tests that don't need network access
- [ ] All 11 previously-failing tests now pass
- [ ] All 55 widget/scroll-nav unit tests still pass
- [ ] All previously-passing integration tests still pass
