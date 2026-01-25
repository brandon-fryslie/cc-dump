# Evaluation: Audit Follow-up Work

## Context
These work items were identified as the top 3 priorities from the comprehensive audit (2026-01-24).

## Work Items

### 1. Add Unit Tests for Core Modules
**Source**: Test Coverage Audit - P0 Critical Gap
**Scope**: analysis.py, formatting.py, router.py
**Current State**: 0% unit test coverage; only E2E hot-reload tests exist
**Impact**: Enables safe refactoring, catches regressions

### 2. Refactor render_block() to Registry Pattern
**Source**: Code Quality Audit - P0 Critical Issue
**Scope**: tui/rendering.py:39 - 137 lines, 38-way if/elif dispatch
**Current State**: Mega-function with cyclomatic complexity of 38
**Impact**: Reduces complexity, enables adding new block types easily

### 3. Create Foundational Documentation
**Source**: Planning Alignment Audit - Critical Gap
**Scope**: ARCHITECTURE.md, PROJECT_SPEC.md
**Current State**: No strategy/architecture docs exist; only README.md
**Impact**: Provides strategic foundation for sprint planning

## Assessment

All three items have HIGH confidence - the work is well-defined:
- Unit tests: Known patterns, clear test targets
- Registry refactor: Standard pattern, clear migration path
- Documentation: Content exists mentally, just needs writing

## Verdict: CONTINUE

No blockers. All items are independent and can be planned as separate sprints.

## Sprint Grouping

| Sprint | Work Item | Confidence | Rationale |
|--------|-----------|------------|-----------|
| 1 | Unit tests | HIGH | Foundation for safe refactoring |
| 2 | Registry refactor | HIGH | Requires tests first for safety |
| 3 | Documentation | HIGH | Can be done in parallel |

Dependencies:
- Sprint 2 (refactor) should follow Sprint 1 (tests) for safety
- Sprint 3 (docs) is independent
