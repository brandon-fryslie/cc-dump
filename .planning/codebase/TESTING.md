# Testing Patterns & Framework — cc-dump

**Project:** cc-dump (Python 3.10+)
**Last Updated:** 2026-04-03
**Scope:** Test framework, structure, mocking, coverage, organization

## 1. Test Framework & Configuration

### Pytest Setup
- **Framework:** pytest 9.0.2+ (pyproject.toml:54)
- **Async support:** pytest-asyncio 0.24.0+ with `asyncio_mode = "auto"`
- **Parallel execution:** pytest-xdist 3.5.0+ (enabled in justfile)
- **PTY testing:** ptydriver 0.2.0+ for subprocess tests

### Configuration (pyproject.toml)
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]           # Single directory for all tests
asyncio_mode = "auto"           # Automatic event loop management
markers = [
    "pty: tests requiring PTY subprocess (slow)",
    "textual: in-process Textual harness tests (fast)",
]
filterwarnings = [
    "ignore:.*use of forkpty\\(\\).*:DeprecationWarning",
]
```

### Running Tests

**All tests (parallel):**
```bash
just test                  # uv run pytest -n auto --dist loadgroup
```

**Single test file:**
```bash
just test tests/test_coerce.py -v
```

**By marker:**
```bash
pytest -m pty              # Slow PTY-based tests
pytest -m textual          # Fast in-process tests
pytest -m "not pty"        # Skip PTY tests
```

**Specific test:**
```bash
just test -k "test_coerce_int_uses_default"
```

**Sequential (no parallelization):**
```bash
just test-seq tests/test_hot_reload.py
```

## 2. Test Organization

### File Structure
- **Location:** `tests/` directory at project root
- **Naming:** `test_*.py` for test modules; `tests/conftest.py` for shared fixtures
- **Count:** ~75 test files as of 2026-04-03
- **Total test functions:** ~175+ across all files

### Directory Organization
```
tests/
├── conftest.py                 # Shared fixtures, setup
├── test_coerce.py              # Unit tests (core/coerce.py)
├── test_token_counter.py       # Unit tests (core/token_counter.py)
├── test_har_recorder.py        # Unit tests (pipeline/har_recorder.py)
├── test_analytics_store.py     # Unit tests (app/analytics_store.py)
├── test_hot_reload.py          # Hot-reload error resilience
├── test_segmentation.py        # Segmentation pipeline
├── test_formatting.py          # Formatting blocks
├── test_input_modes.py         # TUI input handling
├── test_xml_collapse.py        # XML rendering
├── test_textual_navigation.py  # TUI navigation
├── test_session_panel.py       # Session panel
└── ... (65 more)
```

### Test Module Mapping
- **One test file per source module (usually):**
  - `src/cc_dump/core/coerce.py` → `tests/test_coerce.py`
  - `src/cc_dump/core/token_counter.py` → `tests/test_token_counter.py`
  - `src/cc_dump/pipeline/har_recorder.py` → `tests/test_har_recorder.py`
- **Complex modules may have multiple test files:**
  - `src/cc_dump/tui/` has: `test_input_modes.py`, `test_textual_navigation.py`, `test_xml_collapse.py`, etc.

## 3. Test Fixtures & Setup

### Centralized Fixtures (conftest.py)

**Session-scoped fixtures:**
```python
@pytest.fixture(scope="session", autouse=True)
def _init_theme():
    """Initialize default render runtime theme for tests."""
    from textual.theme import BUILTIN_THEMES
    from cc_dump.tui.rendering import set_theme
    set_theme(BUILTIN_THEMES["textual-dark"])
```
- Runs once per test session
- Auto-used (no explicit request needed)
- Sets up rendering backend for all tests

**Function-scoped fixtures:**
```python
@pytest.fixture
def isolated_render_runtime():
    """Provide an isolated, uninitialized render runtime for a test.

    // [LAW:behavior-not-structure] Tests needing fail-fast theme behavior use
    // explicit runtime setup/reset APIs instead of mutating module internals.
    """
    import cc_dump.tui.rendering as rendering

    previous = rendering.reset_render_runtime_for_tests()
    try:
        yield
    finally:
        rendering.set_default_render_runtime(previous)
```
- Isolates rendering state per test
- Yields for test body
- Restores state on cleanup

**Class-scoped fixtures (test optimization):**
```python
@pytest.fixture(scope="class")
def class_proc():
    """One cc-dump process shared across all tests in a class (no port needed)."""
    proc, _port = _launch_cc_dump()
    yield proc
    _teardown_proc(proc)
```
- Shared process across all test methods in a class
- Reduces startup overhead (from per-test to per-class)
- Used in PTY-based tests (e.g., `TestInputModes` class)

### Smart Wait Helpers

**settle() — minimal delay:**
```python
def settle(proc, duration=0.05):
    """Minimal delay after keystroke to let event loop process."""
    time.sleep(duration)
    assert proc.is_alive(), "Process died after keystroke"
```
- Short sleep (0.05s) to allow event processing
- Verifies process is still alive

**wait_for_content() — polling with predicate:**
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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        content = proc.get_content()
        if predicate is None:
            if content and len(content.strip()) >= 10:
                return content
        elif predicate(content):
            return content
        time.sleep(interval)
    return proc.get_content()
```
- Replaces fixed `time.sleep()` patterns
- Configurable timeout and polling interval
- Returns content for inspection

### Process Launch Helpers

**_launch_cc_dump() — starts proxy with TUI:**
```python
def _launch_cc_dump(port=0, timeout=10):
    """Launch cc-dump and wait for TUI to be ready. Returns (proc, port).

    Uses port 0 by default — the OS assigns a free port, eliminating
    collisions when xdist runs multiple workers in parallel.
    """
    cmd = ["uv", "run", "cc-dump", "--port", str(port or 0)]
    proc = PtyProcess(cmd, timeout=timeout)

    # Two-phase wait: any content, then footer fully rendered
    deadline = time.monotonic() + timeout
    content = ""
    while time.monotonic() < deadline:
        time.sleep(0.05)

        if not proc.is_alive():
            content = proc.get_content()
            raise RuntimeError(f"cc-dump failed to start. Error output:\n{content}")

        content = proc.get_content()
        # Footer keywords indicate the TUI is fully rendered
        if content and any(
            kw in content.lower()
            for kw in ("metadata", "tools", "system", "quit")
        ):
            break
    else:
        raise RuntimeError(
            f"cc-dump started but TUI not fully rendered after {timeout}s. Output:\n{content}"
        )

    # Extract actual port from startup output
    match = re.search(r"Listening on: http://[\w.]+:(\d+)", content)
    if match:
        port = int(match.group(1))

    return proc, port
```
- Port 0 → OS-assigned (no collision on xdist workers)
- Two-phase wait: content arrival + TUI readiness (footer keywords)
- Extracts assigned port from output

**_teardown_proc() — graceful shutdown:**
```python
def _teardown_proc(proc):
    """Gracefully quit a cc-dump process."""
    if proc.is_alive():
        try:
            proc.send("q", press_enter=False)
            time.sleep(0.1)
            if proc.is_alive():
                proc.terminate()
        except Exception:
            pass
```

### File Manipulation Fixtures

**backup_file() — context manager for restoration:**
```python
@pytest.fixture
def backup_file():
    """Context manager to backup and restore a file after modification."""
    backed_up = []

    @contextmanager
    def _backup(filepath):
        backup_path = filepath + ".backup"
        shutil.copy2(filepath, backup_path)
        backed_up.append((filepath, backup_path))
        try:
            yield filepath
        finally:
            shutil.move(backup_path, filepath)
            time.sleep(0.05)

    yield _backup

    # Cleanup any remaining backups
    for original, backup in backed_up:
        if os.path.exists(backup):
            shutil.move(backup, original)
```
- Yields a context manager
- Handles fixture-level and cleanup-level teardown

**modify_file() — context manager for temp changes:**
```python
@contextmanager
def modify_file(filepath, modification_fn):
    """Context manager to temporarily modify a file.

    Args:
        filepath: Path to file to modify
        modification_fn: Function that takes file content and returns modified content
    """
    backup_path = str(filepath) + ".temp_backup"
    shutil.copy2(filepath, backup_path)

    try:
        with open(filepath, "r") as f:
            original_content = f.read()

        modified_content = modification_fn(original_content)

        with open(filepath, "w") as f:
            f.write(modified_content)

        time.sleep(0.05)  # Filesystem registration delay
        yield filepath

    finally:
        shutil.move(backup_path, filepath)
        time.sleep(0.05)
```
- Accepts function for content transformation
- Sleeps for filesystem to register change (watchfiles needs this)

### State Fixtures

**fresh_state() — new formatting state:**
```python
@pytest.fixture
def fresh_state():
    """Fresh formatting state."""
    from cc_dump.core.formatting_impl import ProviderRuntimeState
    return ProviderRuntimeState()
```
- Used in `test_formatting.py` (line 67)
- Provides clean slate for each test

## 4. Test Patterns & Structure

### Simple Unit Tests
**test_coerce.py — straightforward functions:**
```python
def test_coerce_int_uses_default_on_invalid_values():
    assert coerce_int("abc", 7) == 7
    assert coerce_int(object(), 3) == 3

def test_coerce_int_accepts_common_scalar_inputs():
    assert coerce_int(True, 0) == 1
    assert coerce_int("12", 0) == 12
    assert coerce_int(12.9, 0) == 12
```
- Direct assertions on function output
- No fixtures needed for pure functions
- Descriptive test names explain scenario

### Test Classes for Grouping
**test_segmentation.py — organized by topic:**
```python
class TestPlainMarkdown:
    def test_inline_tags_produce_single_md(self):
        text = "Hello <world> and <foo bar> stuff"
        result = segment(text)
        assert kinds(result) == ["md"]
        assert result.errors == ()

    def test_no_structure(self):
        text = "Just some **bold** and _italic_ text."
        result = segment(text)
        assert kinds(result) == ["md"]

class TestMdFence:
    def test_empty_info_fence_is_md_fence(self):
        text = "before\n```\nsome *markdown* content\n```\nafter"
        result = segment(text)
        assert kinds(result) == ["md", "md_fence", "md"]
```
- Group related tests in classes
- Class name indicates topic
- Shared setup via class-scoped fixtures if needed

### Integration Tests with Fixtures
**test_formatting.py — uses fresh_state fixture:**
```python
def test_format_request_minimal(fresh_state):
    """Minimal request returns expected blocks."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [],
    }
    blocks = format_request(body, fresh_state)

    # Should have header, metadata, etc.
    assert len(blocks) > 0
    has_header = any(isinstance(b, HeaderBlock) for b in blocks)
    assert has_header
```
- Fixture parameter injected by pytest
- Test body is deterministic given fresh state

### Helper Functions in Tests
**test_segmentation.py — utility functions:**
```python
def kinds(result: SegmentResult) -> list[str]:
    """Extract SubBlock kind values as a list of strings."""
    return [sb.kind.value for sb in result.sub_blocks]

def text_of(raw: str, sb: SubBlock) -> str:
    """Extract the text for a SubBlock from raw text."""
    return raw[sb.span.start : sb.span.end]
```
- Reduce duplication across assertions
- Make assertions more readable
- Not fixtures; pure helper functions

### Parametrized Tests
**Used when testing multiple scenarios:**
```python
@pytest.mark.parametrize("input,expected", [
    ("abc", True),
    ("xyz", False),
])
def test_something(input, expected):
    assert check_something(input) == expected
```
- Clear test IDs generated automatically
- Single implementation for multiple cases

## 5. PTY-Based Tests (Subprocess)

### Markers & Scope
- **Marker:** `@pytest.mark.pty`
- **Speed:** Slow (subprocess startup overhead)
- **Use case:** Integration tests with running cc-dump proxy
- **Example:** `test_input_modes.py`, `test_session_panel.py`

### Example: Input Mode Test
**test_input_modes.py:**
```python
class TestInputModes:
    async def test_navigation_j_scrolls(self, app_and_pilot):
        """j key scrolls down one line."""
        # app_and_pilot fixture manages TUI lifecycle
        ...

    async def test_filter_toggle_1_changes_user(self, app_and_pilot):
        """1 key toggles user visibility."""
        ...
```
- Class-scoped fixture `class_proc` (shared process)
- Async methods (pytest-asyncio)
- Sends keystrokes, checks TUI output

### Process Interaction Pattern
```python
proc.send("j", press_enter=False)           # Send 'j' key
settle(proc, duration=0.05)                 # Wait for processing
content = proc.get_content()                # Get terminal output
assert "search" in content.lower()          # Check for expected output
```

## 6. Error Handling & Resilience Tests

### Hot-Reload Error Resilience
**test_hot_reload.py — mocked reload failures:**
```python
class TestHotReloadErrorResilience:
    """Test that hot-reload handles module errors gracefully."""

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
- Mocks `importlib.reload()` to simulate errors
- Verifies hot-reload continues despite module error
- Checks that unbroken modules still reload

### Validation Tests
**test_har_recorder.py — input validation:**
```python
def test_build_har_request_basic():
    """HAR request builder creates valid structure."""
    headers = {"content-type": "application/json"}
    body = {"model": "claude-3-opus-20240229", "messages": []}

    har_req = build_har_request(
        "POST", "https://api.anthropic.com/v1/messages", headers, body
    )

    # Verify structure
    assert har_req["method"] == "POST"
    assert har_req["httpVersion"] == "HTTP/1.1"
    assert isinstance(har_req["headers"], list)
```
- Tests that builders create valid HAR structures
- No mocking; direct API testing

## 7. Mocking & Patching

### unittest.mock Usage
- **Module:** `from unittest.mock import patch, Mock, AsyncMock`
- **Scope:** External dependencies, subprocess, file I/O
- **Pattern:** `with patch.object(module, 'attribute', side_effect=...)`

### Example: Module Reload Mocking
```python
with patch.object(importlib, "reload", side_effect=failing_reload):
    reloaded = hr.check_and_get_reloaded()
```
- `side_effect=callable`: Callable receives call args, returns value or raises
- Context manager: Restores original on exit

### Example: File System Testing
```python
def test_har_subscriber_writes_file(tmp_path):
    """HAR recording writes a HAR 1.2 file."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))
    # ... send events ...
    subscriber.close()

    assert har_path.exists()
    with open(har_path) as f:
        har_data = json.load(f)
    assert har_data["version"] == "1.2"
```
- `tmp_path` fixture: Temporary directory, auto-cleaned
- Direct file I/O testing without mocks

## 8. Coverage & Quality

### Quality Gate
- **Command:** `just quality-gate` (runs `scripts/quality_gate.py check`)
- **Purpose:** Detect regressions in lint, complexity vs. baseline
- **Refresh:** `just quality-gate-refresh` (update acceptable baselines)

### Known Warnings
- **Deprecation warnings (forkpty):** Filtered in pytest config
  ```python
  filterwarnings = [
      "ignore:.*use of forkpty\\(\\).*:DeprecationWarning",
  ]
  ```
  - From ptydriver (not our code)
  - Suppressed to keep test output clean

### Known Test Limitations
- **2 skipped tests:** DB-related stubs, not failures (as of 2026-02-07 optimization)
- **15+ warnings:** All forkpty deprecation from ptydriver
- **No coverage goal specified:** Quality gate focuses on lint/complexity

## 9. Test Suite Performance

### Recent Optimization (2026-02-07)
- **Before:** ~254 seconds
- **After:** ~113 seconds
- **Speedup:** 2.2x via class-scoped fixtures, polling waits, faster startup polling

### Techniques
1. **Class-scoped fixtures:** Process shared across all tests in a class
2. **Polling waits:** Replace fixed sleep with `wait_for_content(predicate)` (0.05s intervals)
3. **Faster startup polling:** 0.05s vs. 0.5s initial check
4. **TUI readiness:** Wait for footer keywords ("headers", "tools", "system", "quit")

### Timing Guidelines
- **Hot-reload tests:** ≥1.5s waits (1s idle check interval + margin)
- **Import error test:** 2.0s wait needed
- **TUI startup:** Fast polling (0.05s) + readiness check (footer keywords)

## 10. Async Testing (pytest-asyncio)

### Configuration
- **Mode:** `asyncio_mode = "auto"` (pyproject.toml:61)
- **Behavior:** Event loop auto-created and torn down per test
- **Syntax:** `async def test_*`, `await async_call()`

### Example: Async Widget Test
```python
class TestInputModes:
    async def test_navigation_j_scrolls(self, app_and_pilot):
        """j key scrolls down one line."""
        app, pilot = app_and_pilot
        await pilot.press("j")
        # ... assertions ...
```

### Fixtures for Async
- **app_and_pilot:** Provides Textual app + pilot for interaction
- **Automatic event loop:** No manual loop creation needed

## 11. Debugging Failed Tests

### Verbose Output
```bash
pytest tests/test_coerce.py -v        # Verbose: show test names
pytest tests/test_coerce.py -vv       # Very verbose: show full output
pytest tests/test_coerce.py -s        # Show print() output
```

### Capture Output Control
- **-s flag:** Show stdout/stderr (instead of capturing)
- **caplog fixture:** Capture and inspect log records
- **capsys fixture:** Capture sys.stdout/stderr

### Stop on First Failure
```bash
pytest -x tests/                      # Stop after first failure
pytest -x --tb=short tests/           # Short traceback
pytest -x --tb=long tests/            # Full traceback with context
```

### Interactive Debugging
```python
def test_something():
    import pdb; pdb.set_trace()  # Breakpoint
    # ... test code ...
```

## 12. Common Patterns & Anti-Patterns

### ✅ Good Patterns

**Descriptive test names:**
```python
def test_coerce_int_uses_default_on_invalid_values():
    assert coerce_int("abc", 7) == 7
```

**Fixture-based setup:**
```python
def test_formatting_with_state(fresh_state):
    blocks = format_request(body, fresh_state)
    assert len(blocks) > 0
```

**Grouped assertions (logically independent):**
```python
def test_har_response_structure():
    har_resp = build_har_response(200, {}, msg, 1234.5)
    assert har_resp["status"] == 200
    assert har_resp["httpVersion"] == "HTTP/1.1"
    assert har_resp["content"]["mimeType"] == "application/json"
```

**Smart waits (polling):**
```python
content = wait_for_content(proc, timeout=3, interval=0.05)
assert "expected_text" in content
```

### ❌ Anti-Patterns

**Fixed sleep times:**
```python
# BAD: Flaky on slow machines, wastes time on fast ones
time.sleep(1)
content = proc.get_content()
```

**Silent error swallowing:**
```python
# BAD: Test passes even if proc dies
try:
    content = proc.get_content()
except Exception:
    pass
assert "text" in content  # Fails cryptically
```

**Overly broad mocks:**
```python
# BAD: Mocking internal implementation, not boundary
with patch.object(coerce, "isinstance"):
    test_coerce_int()
```

**Unrelated multiple assertions:**
```python
# BAD: If first assertion fails, rest don't run
def test_multiple_unrelated_things():
    assert func1() == 1
    assert func2() == 2
    assert func3() == 3  # Never runs if func1 fails
```

---

## Summary

cc-dump's testing approach emphasizes:

1. **Centralized fixtures:** conftest.py owns setup; reusable across suite
2. **Smart waits:** Polling-based, not fixed sleeps; reduces flakiness and runtime
3. **Class-scoped processes:** Optimization for PTY tests; reduces startup overhead
4. **Descriptive naming:** Test name explains scenario and assertion
5. **Error resilience:** Mocked tests for error handling; real processes for integration
6. **Clean separation:** Unit tests (fast), PTY tests (slow), async tests (Textual)
7. **Markers for grouping:** `@pytest.mark.pty` / `@pytest.mark.textual` for selective runs
8. **Type-safe events:** Event dataclasses tested via `isinstance()` checks
9. **Quality gates:** Regression detection on lint/complexity, not just coverage
10. **Performance focus:** 2.2x suite speedup via optimization; tests run in ~113s

Tests are **behavior-focused** (not structure), with the goal of **early detection of regressions** and **confidence in refactoring**.
