# Code Conventions — cc-dump

**Project:** cc-dump (Python 3.10+)
**Last Updated:** 2026-04-03
**Scope:** Style, naming, patterns, error handling across src/ and tests/

## 1. Module and File Organization

### Naming
- **Module names:** lowercase with underscores: `formatting_impl.py`, `token_counter.py`, `widget_factory.py`
- **Packages:** lowercase: `src/cc_dump/core/`, `src/cc_dump/tui/`, `src/cc_dump/pipeline/`
- **Private modules:** Prefixed with underscore: `_impl.py` facades (e.g., `src/cc_dump/core/formatting.py` wraps `formatting_impl.py`)

### Layout Convention
- **Docstrings at module top:** Always present, often cite architectural laws with `// [LAW:...]` comments
- **Import order:**
  1. `from __future__ import annotations` (PEP 563 — quasi-universal in codebase)
  2. Standard library (sorted)
  3. Third-party (sorted): `textual`, `pydantic`, `snarfx`, etc.
  4. Local imports: `cc_dump.*` modules
- **Module-level imports for hot-reload:** `import cc_dump.module` (never `from cc_dump.module import X`)
  - Exception: `from cc_dump.module import SomeType` is acceptable for type-only imports
  - See `src/cc_dump/tui/app.py` (lines 32–74) for pattern

### File Size & Cohesion
- **Split by change-reason, not size:** Modules stay focused on one concept
  - Example: `formatting.py` (facade) delegates to `formatting_impl.py` (impl)
  - Example: `rendering.py` (high-level dispatch) + `rendering_impl.py` (block-specific renderers)
- **No "where things go" dumping grounds:** If a module becomes miscellaneous, split it

## 2. Naming Conventions

### Variables, Functions, Classes
- **snake_case for functions/variables:** `def coerce_int()`, `turn_budget`, `msg_events`
- **PascalCase for classes:** `FormattedBlock`, `AnalyticsStore`, `ErrorItem`, `ProviderRuntimeState`
- **UPPER_CASE for module constants:** `_RELOAD_ORDER`, `_ROLE_TOKEN_FIELDS`, `_USER_ID_PATTERN`
- **Single underscore prefix for module-private:** `_impl` module, `_setup_and_trigger()` test helper
- **Double underscore prefix (rare):** Used for name mangling in classes; prefer single underscore

### Type Aliases
- Defined at module top, PascalCase or descriptive lowercase
  - `JsonDict = dict[str, object]` (event_types.py, line 18)
  - `_ContentBlockDict = dict[str, str | int | dict | list | None]` (formatting_impl.py, line 33)

### Enum Members
- **CamelCase within Enum classes:** `END_TURN`, `TOOL_USE`, `MAX_TOKENS`
- **Value is lowercase string:** `END_TURN = "end_turn"`, `USER = "user"`

### Test Functions & Classes
- **test_* naming:** `test_coerce_int_uses_default_on_invalid_values()` (coerce, line 6)
- **Descriptive names:** Describe the scenario and assertion in function name
- **Test classes:** `Test*` prefix for grouping related tests
  - Example: `TestPlainMarkdown`, `TestMdFence` (segmentation.py)
  - Example: `TestHotReloadErrorResilience` (test_hot_reload.py, line 22)

## 3. Type Hints & Annotations

### Universal Adoption
- **All function signatures:** Fully type-hinted (enforced by mypy)
- **Variable annotations:** Used liberally for clarity, especially in dataclass fields
- **Modern syntax (PEP 604):** `int | None` instead of `Optional[int]`
- **`from __future__ import annotations` is quasi-universal:** Enables forward references

### Examples from Codebase
```python
# Function signature (coerce.py:11–19)
def coerce_int(value: object, default: int = 0) -> int:
    ...

# Optional return (coerce.py:22–30)
def coerce_optional_int(value: object) -> int | None:
    ...

# Complex return type (cli.py:44–46)
def _detect_run_subcommand(argv: list[str]) -> tuple[str | None, list[str], list[str]]:
    ...

# Dataclass with frozen and type hints (event_types.py:70–77)
@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
```

### MyPy Configuration
- **Strict mode:** `check_untyped_defs = true`, `disallow_any_explicit = true`
- **Exceptions (disabled error codes):**
  - `dict-item`: Rendering dispatch table signature mismatches (27 errors)
  - `arg-type`: List variance, tuple element types (26 errors)
  - `union-attr`: Accessing attrs on Optional without narrowing (23 errors)
  - `attr-defined`: Dynamic attrs (_expandable, _xml_strip_ranges, etc., 18 errors)
- **Run:** `uv run mypy src/` (see justfile, line 36)

## 4. Docstrings

### Style & Content
- **Module-level docstrings:** Present on all Python files, often cite architectural laws
  - Location: Top of file after shebang/encoding
  - Example from `coerce.py`:
    ```python
    """Shared scalar/map coercion helpers.

    // [LAW:one-source-of-truth] Common coercion behavior is centralized here.
    """
    ```

- **Function docstrings:** Present for public/exported functions
  - Format: One-liner + optional Args/Returns sections
  - Example from `conftest.py:wait_for_content()` (lines 52–74):
    ```python
    def wait_for_content(proc, predicate=None, timeout=3, interval=0.05):
        """Poll until content matches predicate or timeout.

        Args:
            proc: PtyProcess to poll
            predicate: Optional callable(content) -> bool. If None, waits for
                       any non-trivial content (>=10 chars).
            timeout: Max seconds to wait
            interval: Polling interval in seconds

        Returns:
            The content string at the time of match or timeout.
        """
    ```

- **Class docstrings:** Present on dataclasses and public classes
  - Explain purpose, invariants, and important fields
  - Example from `formatting_impl.py:VisState` (lines 78–86):
    ```python
    class VisState(NamedTuple):
        """Visibility state for a block — three orthogonal boolean axes.

        // [LAW:one-source-of-truth] THE representation of visibility.
        // [LAW:dataflow-not-control-flow] Values, not control flow branching.
        """
        visible: bool  # False = hidden, True = shown
        full: bool     # False = summary level, True = full level
        expanded: bool # False = collapsed, True = expanded
    ```

- **Architectural Law Citations:** Many docstrings include `// [LAW:token] reason` comments
  - Example: `// [LAW:one-source-of-truth]`, `// [LAW:dataflow-not-control-flow]`
  - See: CLAUDE.md `/universal-laws` section for law list

### Comment Style
- **Inline comments:** Sparingly; explain *why*, not *what*
  - Code should be self-explanatory via naming
  - Use comments for non-obvious intent
- **Section headers:** Two-line blocks with UTF-8 box-drawing or ASCII
  - Example from `conftest.py` (line 14):
    ```python
    # ---------------------------------------------------------------------------
    # Theme initialization — configure default render runtime before tests run
    # ---------------------------------------------------------------------------
    ```

## 5. Error Handling & Exceptions

### Patterns
- **No silent fallbacks:** Errors are raised loudly; never swallowed with `except: pass`
- **Defensive null guards minimized:** Check at trust boundaries (external input, network)
  - Example from `coerce.py`: Type-check inputs, return defaults instead of raising
  - Not enforced at callsites; architecture prevents null by design
- **Fail-fast on invalid data:** Let errors surface rather than propagate garbage

### Examples from Codebase

**Coerce module (coerce.py:11–19):** Returns defaults on parse failure
```python
def coerce_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default  # Explicit default on error
    return default
```

**Event parsing (event_types.py):** Validation at single boundary
```python
# [LAW:single-enforcer] parse_sse_event is the sole SSE validation boundary.
```

**Hot-reload error resilience (test_hot_reload.py:40–52):** Errors logged, reload continues
```python
def test_survives_syntax_error_in_module(self):
    """Reload continues past a module that raises SyntaxError."""
    hr = self._setup_and_trigger()

    def failing_reload(mod):
        if mod.__name__ == "cc_dump.core.palette":
            raise SyntaxError("simulated syntax error")
        return mod

    with patch.object(importlib, "reload", side_effect=failing_reload):
        reloaded = hr.check_and_get_reloaded()

    assert "cc_dump.core.palette" not in reloaded, "Broken module should be skipped"
    assert len(reloaded) > 0, "Other modules should still reload"
```

### Logging
- **Logger per module:** `logger = logging.getLogger(__name__)` (top of file)
- **Setup centralized:** `io/logging_setup.py` (lines 1–5)
  - Sets up rotating file handlers, stream handlers
  - Single enforcer for handler wiring
  - Environment variable: `CC_DUMP_LOG_DIR`

## 6. Data Structures & Patterns

### Dataclasses
- **Ubiquitous:** Primary data container pattern
- **Frozen where possible:** `@dataclass(frozen=True)` for value types
  - Example: `Usage` (event_types.py:70–77)
  - Example: `ErrorItem` (error_models.py:9–13)
- **With defaults:** Field defaults via `field()` or type annotation default
  - Example: `@dataclass class TurnBudget: system_tokens_est: int = 0`

### Enums
- **Discriminator use:** For type-safe variant selection
  - Example: `PipelineEventKind`, `StopReason`, `Category` (event_types.py)
  - Example: `Level` (IntEnum in formatting)

### NamedTuples
- **Lightweight value holders:** Use when immutability is critical
  - Example: `VisState(visible, full, expanded)` (formatting_impl.py:78–86)

### Type-Safe Event System
- **Event class IS the type:** No string discriminator field
  - Example: `RequestHeadersEvent`, `ResponseCompleteEvent` (pipeline/event_types.py)
  - Dispatch via `isinstance()` checks or type guards

## 7. Imports & Dependencies

### Hot-Reload Safe Imports
- **Stable modules:** Import via `import cc_dump.module` (module-object reference)
  - Reloadable code can patch module attributes (functions, classes)
  - Example from `app.py` (lines 32–74): All reloadable modules imported as `import cc_dump.X`
- **Reloadable modules:** List in `hot_reload.py` (`_RELOAD_ORDER`)
- **Never from-import reloadable symbols:**
  - ❌ `from cc_dump.formatting import format_request`
  - ✅ `import cc_dump.core.formatting` → `cc_dump.core.formatting.format_request()`

### Stable Module Boundaries
- **Never hot-reloaded:** Type defs, protocols, stable event types
  - `pipeline/event_types.py`: "STABLE — never hot-reloaded"
  - `core/palette.py`: Core color constants
  - Comment at top: "// [LAW:one-source-of-truth] Safe for `from` imports everywhere"

### Circular Imports
- **Avoided via module-level imports:** Stable boundary modules prevent cycles
- **TYPE_CHECKING guards:** Used for optional imports
  - Example from `widget_factory.py`:
    ```python
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from cc_dump.tui.protocols import SomeProtocol
    ```

## 8. Code Style

### Line Length & Formatting
- **Ruff formatter:** `uv run ruff format src/` (justfile, line 60)
- **Ruff linter:** `uv run ruff check src/` (justfile, line 24)
- **No explicit line length configured:** Ruff defaults apply (~88 char soft limit)

### Whitespace & Blank Lines
- **Two blank lines:** Between top-level definitions (PEP 8)
- **One blank line:** Between methods in a class
- **Logical grouping:** Blank lines separate logical sections within functions

### String Formatting
- **f-strings preferred:** Modern Python style
  - Example: `f"cc-dump-{ts}-{os.getpid()}.log"` (logging_setup.py:42)
- **Multiline strings:** Triple-quoted; formatted with proper indentation

### Dictionary/List Literals
- **Trailing commas:** Used in multiline definitions for clean diffs
- **Reasonable spread:** Keep literals readable; split large dicts/lists

### Comprehensions
- **Preferred over explicit loops:** When condition is simple
- **Nested sparingly:** Break into steps if nesting > 2 levels

## 9. Testing Patterns

### Test Organization
- **Flat directory:** Tests in `tests/` (see justfile, `testpaths = ["tests"]`)
- **One test file per module:** `test_coerce.py` for `core/coerce.py`
- **Grouped by class or category:** Logical sections with comments

### Test Naming
- **test_* prefix:** All test functions/methods
- **Descriptive action + assertion:** `test_coerce_int_uses_default_on_invalid_values()`
- **Avoid "happy path":** Name specifics of the test scenario

### Fixtures
- **Centralized in conftest.py:** Shared across test suite
- **Scope decorator:** `@pytest.fixture(scope="session")`, `@pytest.fixture(scope="class")`
- **Purposeful naming:**
  - `fresh_state`: ProviderRuntimeState instance
  - `class_proc`: One cc-dump process per test class
  - `isolated_render_runtime`: Reset rendering state for isolation
  - `backup_file`: Context manager for file restoration

### Markers
- **pty:** Tests requiring PTY subprocess (slow)
- **textual:** In-process Textual harness tests (fast)
- **Filtering:** Run with `pytest -m pty` or `pytest -m textual`

### Async Tests
- **pytest-asyncio mode:** `asyncio_mode = "auto"` (pyproject.toml:61)
- **async def test_*:** Automatic event loop management

### Parametrization
- **pytest.mark.parametrize:** Used when testing multiple inputs
  - Clear test names from parameter IDs

### Mock & Patch
- **unittest.mock.patch:** Standard library, no extra dependency
- **Mocking boundaries:** Mock external systems, not internal logic
  - Example: Mock `importlib.reload()` in hot-reload error tests (test_hot_reload.py)

### Assertions
- **Explicit assertions:** `assert condition, "message"`
- **Multiple assertions per test acceptable:** If logically grouped and independent
- **Use pytest helpers:** `assert x in y`, `assert x == y` (not manual comparison)

### Smart Wait Patterns
- **Polling waits:** Avoid fixed `time.sleep()`
- **conftest.py helpers:**
  - `settle(proc, duration=0.05)`: Minimal event-loop delay
  - `wait_for_content(proc, predicate=None, timeout=3, interval=0.05)`: Poll with predicate

## 10. Architectural Patterns (Enforced)

### Law: One Source of Truth
- **Single canonical representation:** Canonical implementation in `_impl.py`
- **Facade pattern:** Public API in `.py`, impl in `_impl.py`
  - Example: `formatting.py` ⟷ `formatting_impl.py`
- **No divergent copies:** All consumers use one path

### Law: Dataflow, Not Control Flow
- **Operations always execute:** Variability lives in values (nulls, empty collections)
- **No conditional operation skipping:** If branching guards an operation, restructure
- **Example (analysis.py:31–48):** Compact token formatting derives from magnitude, not branching
  ```python
  suffix_steps = (
      (1_000_000_000, "B"),
      (1_000_000, "M"),
      (1_000, "k"),
  )
  for threshold, suffix in suffix_steps:
      if abs_value >= threshold:
          scaled = abs_value / threshold
          number = f"{scaled:.1f}".rstrip("0").rstrip(".")
          return f"{sign}{number}{suffix}"
  return f"{value}"
  ```

### Law: Single Enforcer
- **Cross-cutting invariants:** Enforced at exactly one boundary
  - Example: SSE parsing — `parse_sse_event()` is sole validation boundary (event_types.py)
  - Example: Logger setup — `logging_setup.py` is sole handler wiring point
- **No duplicate checks:** Scattered validation is deferred to the enforcer

### Law: One-Way Dependencies
- **Upward calls forbidden:** No cycles, no backlinks
- **Test import pattern:** Tests can import anything; codebase enforces layering
- **Module organization:** `core/` → `pipeline/` → `tui/`, no reverse

### Law: One Type Per Behavior
- **Before creating FooA, FooB, FooC:** Ask "what differs besides the name?"
- **If answer is "only config":** Use one Foo with instances/config
- **Example:** Single `FormattedBlock` hierarchy, not separate Block classes for each type

## 11. Common Code Organization Patterns

### Pure Computation Modules
- **No I/O, no state, no cc_dump dependencies:** Safe to import anywhere
- **Example:** `core/analysis.py` (lines 1–5)
  ```python
  """Context analytics — token estimation, turn budgets, and tool correlation.

  Pure computation module with no I/O, no state, and no dependencies on other
  cc_dump modules.
  """
  ```

### Stable vs. Reloadable Classification
- **Stable (never reload):**
  - Event types, protocols, type aliases
  - Initialization-only modules (logging, settings)
  - Comment: `# This module is STABLE — never hot-reloaded`
- **Reloadable (on file change):**
  - Formatting logic, rendering, widgets, handlers
  - Comment: `# This module is RELOADABLE`

### Facade Modules
- **Single public interface:** Re-exports from implementation module
- **Use `__getattr__` for dynamic delegation:** Stable boundary for hot-reload
- **Example:** `formatting.py` (lines 12–20)
  ```python
  def __getattr__(name: str):
      return getattr(_impl, name)

  def __dir__() -> list[str]:
      return sorted(set(globals()) | set(dir(_impl)))

  __all__ = [name for name in dir(_impl) if not name.startswith("__")]
  ```

### Test Helpers
- **Utility functions in conftest.py:** Shared across test suite
- **Context managers for setup/teardown:** `@contextmanager` decorator
- **Fixture factories:** Parameterized fixtures for repeated patterns

## 12. Linting & Quality Gates

### Ruff Configuration
- **Check & format:** Commands in justfile
  - `just lint`: `uv run ruff check src/`
  - `just fmt`: `uv run ruff format src/`
- **No explicit ruff config file:** Uses pyproject.toml defaults

### MyPy Configuration
- **Run:** `just check` or `uv run mypy src/`
- **Strict settings:** See section 3 above
- **Stubs directory:** `stubs/` for type information

### Quality Gate
- **Regression detection:** `just quality-gate`
  - Runs `scripts/quality_gate.py check`
  - Fails if lint/complexity regressions detected vs. baseline
- **Refresh baselines:** `just quality-gate-refresh`
  - Intentional baseline update when new regressions are acceptable

---

## Summary

cc-dump enforces **strong conventions** around:
1. **Module organization:** One concept per file; hot-reload-safe imports
2. **Type safety:** Universal hints, strict mypy, modern syntax (PEP 604)
3. **Data-first design:** Dataclasses, enums, type-safe events
4. **Architectural laws:** Single enforcers, one source of truth, dataflow over control flow
5. **Testing discipline:** Descriptive names, smart waits, fixture reuse, class-scoped processes
6. **Error handling:** No silent fallbacks; explicit defaults and fail-fast validation
7. **Documentation:** Module docstrings with law citations; function docstrings on public APIs

These conventions support the project's goals: **observability, maintainability, hot-reload safety, and type security**.
