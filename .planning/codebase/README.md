# Codebase Analysis Documentation

**Generated:** 2026-04-03  
**Project:** cc-dump — HTTP proxy for Claude Code API monitoring with Textual TUI  
**Scope:** Code style, testing patterns, architectural conventions

## Documents

### 1. CONVENTIONS.md (454 lines)
Comprehensive guide to code style and naming conventions.

**Coverage:**
- Module and file organization (layout, imports, hot-reload patterns)
- Naming conventions (snake_case, PascalCase, Enums, test functions)
- Type hints and annotations (universal adoption, mypy strict mode)
- Docstrings (module, function, class docstrings with architectural law citations)
- Error handling patterns (no silent fallbacks, defensive guards at boundaries)
- Data structures (dataclasses, enums, NamedTuples, type-safe events)
- Imports and dependencies (hot-reload safety, stable boundaries, circular imports)
- Code style (ruff formatter/linter, whitespace, strings, comprehensions)
- Testing patterns (naming, fixtures, async, parametrization, mocking)
- Architectural patterns enforced (law citations: one source of truth, dataflow not control flow, single enforcer, one-way dependencies, one type per behavior)
- Common patterns (pure computation modules, stable vs. reloadable, facades, test helpers)
- Linting and quality gates (ruff, mypy, quality gate regression detection)

**Key Takeaways:**
- Universal type hints with strict mypy; modern syntax (PEP 604)
- Architectural laws (from CLAUDE.md) embedded in source with `// [LAW:token]` comments
- Module-level imports for hot-reload safety; one source of truth enforced
- Dataclasses for data containers; enums for type-safe variants
- No silent fallbacks; fail-fast validation at trust boundaries
- Ruff for formatting/linting; quality gate for regression detection

### 2. TESTING.md (696 lines)
Comprehensive guide to testing framework, structure, and patterns.

**Coverage:**
- Test framework and configuration (pytest 9.0.2+, pytest-asyncio, pytest-xdist, ptydriver)
- Test organization (75 test files, ~175 test functions, one-per-module mapping)
- Fixtures and setup (session-scoped _init_theme, function-scoped isolated_render_runtime, class-scoped class_proc)
- Smart wait helpers (settle() for minimal delay, wait_for_content() for polling)
- Process launch helpers (_launch_cc_dump, _teardown_proc, port 0 for xdist)
- File manipulation fixtures (backup_file, modify_file context managers)
- Test patterns (simple units, classes for grouping, integration tests, parametrization, helpers)
- PTY-based tests (subprocess integration, markers @pytest.mark.pty)
- Error resilience tests (hot-reload error handling, validation tests)
- Mocking and patching (unittest.mock for external dependencies)
- Coverage and quality (quality gate for regressions, known warnings filtered)
- Performance optimization (2.2x speedup via class-scoped fixtures, polling waits, faster startup)
- Async testing (pytest-asyncio auto mode)
- Debugging failed tests (verbose output, caplog, capsys, pdb)
- Common patterns and anti-patterns (good: descriptive names, fixtures, smart waits; bad: fixed sleeps, silent errors, overly broad mocks)

**Key Takeaways:**
- Centralized fixtures in conftest.py; reusable across suite
- Smart polling waits (no fixed sleeps); ~113s suite runtime after optimization
- Class-scoped processes for PTY tests; reduces startup overhead
- Descriptive test names explain scenario and assertion
- Markers for grouping: @pytest.mark.pty (slow, subprocess), @pytest.mark.textual (fast, in-process)
- Type-safe events tested via isinstance() checks
- Quality gate for lint/complexity regression detection
- Tests are behavior-focused, not structure-focused

## How to Use This Documentation

### For New Contributors
1. Start with **CONVENTIONS.md** § 1–4: Module organization, naming, types, docstrings
2. Read **CONVENTIONS.md** § 10: Architectural patterns (understand the "why")
3. Read **TESTING.md** § 1–4: Framework, organization, fixtures
4. Check project CLAUDE.md for architectural laws referenced in comments

### For Code Review
- **CONVENTIONS.md** § 3, 5, 6: Type hints, error handling, data structures
- **CONVENTIONS.md** § 8: Code style (ruff, mypy, quality gate)
- **TESTING.md** § 4, 12: Test patterns and anti-patterns
- Verify law citations in comments align with CLAUDE.md

### For Test Writing
- **TESTING.md** § 2–4: Organization, fixtures, patterns
- **TESTING.md** § 9–10: PTY tests, performance, async, debugging
- **TESTING.md** § 12: Anti-patterns to avoid

### For Refactoring
- **CONVENTIONS.md** § 10: Verify architectural laws are maintained
- **TESTING.md** § 8: Ensure error resilience via mocked tests
- Check hot-reload safety (module imports, stable boundaries)

## Statistics

| Document | Lines | Sections |
|----------|-------|----------|
| CONVENTIONS.md | 454 | 12 |
| TESTING.md | 696 | 12 |
| **Total** | **1,150** | **24** |

## Links to Source

### Key Source Files Referenced
- `src/cc_dump/core/coerce.py` — Simple type coercion (conventions)
- `src/cc_dump/core/formatting.py` — Facade pattern (conventions)
- `src/cc_dump/core/formatting_impl.py` — Implementation, VisState (conventions)
- `src/cc_dump/pipeline/event_types.py` — Type-safe events, stable boundary (conventions, testing)
- `src/cc_dump/tui/app.py` — Hot-reload-safe imports (conventions)
- `src/cc_dump/io/logging_setup.py` — Single enforcer pattern (conventions)
- `tests/conftest.py` — Fixtures, process launch, wait helpers (testing)
- `tests/test_coerce.py` — Simple unit tests (testing)
- `tests/test_hot_reload.py` — Error resilience via mocking (testing)
- `tests/test_segmentation.py` — Test classes, helper functions (testing)

### Configuration Files Referenced
- `pyproject.toml` — Pytest config, mypy settings, dependencies
- `justfile` — Common commands (test, lint, format, type-check)
- `CLAUDE.md` — Architectural laws, project instructions

---

**Last reviewed:** 2026-04-03
**Confidence:** High (analyzed 75+ test files, 60+ source modules, configurations)
