# cc-dump Test Suite

Comprehensive integration and unit tests for cc-dump TUI functionality.

## Test Organization

### Integration Tests (`test_tui_integration.py`)

Tests complete user workflows and TUI functionality:

- **TUI Startup/Shutdown**: Basic process lifecycle
- **Filter Toggles**: All keybinding filters (h, t, s, e, m)
- **Panel Toggles**: Stats, Economics, Timeline, Logs panels
- **Request Handling**: API request processing and display
- **Database Integration**: Database persistence and querying
- **Content Filtering**: Verify content visibility changes with filters
- **Stats Panel**: Token counts and statistics display
- **Error Handling**: Resilience to malformed requests
- **Rendering Stability**: Performance under load
- **Complete Workflows**: End-to-end user scenarios

### Visual Indicators Tests (`test_visual_indicators.py`)

Tests the colored bar indicators for filtered content:

- **Filter Indicator Rendering**: Colored bars (▌) for each filter type
  - Cyan for Headers
  - Blue for Tools
  - Yellow for System
  - Green for Expand/Context
  - Magenta for Metadata
- **Indicator Visibility**: Appear/disappear based on filter state
- **Rendering Performance**: Stability under filter toggling
- **Block Rendering**: Individual block types render correctly
- **Color Scheme**: Consistent colors for same filter types
- **Helper Functions**: Unit tests for indicator functions

### Hot Reload Tests (`test_hot_reload.py`)

Tests hot-reload functionality (existing):

- Module reload detection
- Widget swapping
- Error resilience
- Import validation

### Unit Tests

- `test_analysis.py`: Analysis functions
- `test_formatting.py`: Formatting logic
- `test_router.py`: Routing functionality

## Running Tests

### Run All Tests

```bash
uv run pytest
```

### Run Specific Test File

```bash
uv run pytest tests/test_tui_integration.py -v
```

### Run Specific Test Class

```bash
uv run pytest tests/test_tui_integration.py::TestFilterToggles -v
```

### Run Specific Test

```bash
uv run pytest tests/test_tui_integration.py::TestFilterToggles::test_toggle_headers_filter -v
```

### Run with Coverage

```bash
uv run pytest --cov=cc_dump --cov-report=html
```

### Run Only Integration Tests

```bash
uv run pytest tests/test_tui_integration.py tests/test_visual_indicators.py -v
```

### Run Only Unit Tests

```bash
uv run pytest tests/test_analysis.py tests/test_formatting.py -v
```

## Test Development

### Adding New Tests

1. **Integration Tests**: Add to `test_tui_integration.py`
   - Create a new test class for related functionality
   - Use `start_cc_dump` fixture to start TUI
   - Use `proc.send()` to simulate keypresses
   - Use `proc.get_content()` to inspect output
   - Always verify `proc.is_alive()` for stability

2. **Unit Tests**: Add to appropriate file or create new
   - Import the module being tested
   - Test individual functions in isolation
   - Use pytest fixtures for setup/teardown

### Fixtures

- `start_cc_dump`: Start cc-dump TUI process
  - Returns PtyProcess for interaction
  - Handles cleanup automatically
  - Optional `port`, `db_path`, `session_id` parameters

- `temp_db`: Create temporary database file
  - Returns path to temp database
  - Automatically cleaned up after test

- `backup_file`: Backup/restore files for hot-reload tests

### Best Practices

1. **Always check process is alive**: `assert proc.is_alive()`
2. **Add delays after actions**: `time.sleep(0.3)` after key sends
3. **Use random ports**: Avoid port conflicts between tests
4. **Clean up resources**: Use fixtures for automatic cleanup
5. **Test both positive and negative cases**: Enable/disable, show/hide
6. **Document what you're testing**: Clear docstrings
7. **Keep tests independent**: Don't rely on test execution order

## Continuous Integration

Tests run automatically on:
- Every push to main branch
- Every pull request
- Manual workflow dispatch

See `.github/workflows/test.yml` for CI configuration.

## Test Coverage

Current coverage focuses on:
- ✅ TUI startup and shutdown
- ✅ All filter keybindings
- ✅ All panel toggles
- ✅ Visual indicators for filtered content
- ✅ Request handling and display
- ✅ Error resilience
- ✅ Hot reload functionality
- ✅ Rendering stability
- ⏸️ Database integration (requires enhanced fixtures)
- ⏸️ Streaming responses (requires mock API)

## Debugging Tests

### View Test Output

```bash
uv run pytest -v -s
```

The `-s` flag shows print statements and process output.

### Run Single Test in Debug Mode

```bash
uv run pytest tests/test_tui_integration.py::TestFilterToggles::test_toggle_headers_filter -v -s
```

### Inspect Process Content

Add this to your test:

```python
content = proc.get_content()
print("\n=== PROCESS OUTPUT ===")
print(content)
print("=== END OUTPUT ===\n")
```

### Keep Process Running

Comment out the cleanup in conftest.py to keep the TUI running after test:

```python
# for proc in processes:
#     if proc.is_alive():
#         proc.send("q", press_enter=False)
```

## Known Limitations

1. **Terminal Rendering**: PTY output may differ from real terminal
2. **Timing Sensitivity**: Tests use time.sleep() which can be flaky
3. **No Real API**: Tests don't connect to actual Anthropic API
4. **Database Tests**: Some database tests require enhanced fixtures

## Future Improvements

- [ ] Add database-enabled integration tests
- [ ] Mock Anthropic API for streaming response tests
- [ ] Add performance benchmarks
- [ ] Test with different terminal sizes
- [ ] Add screenshot comparison tests
- [ ] Test accessibility features
- [ ] Add stress tests (long-running sessions)
- [ ] Test memory usage and leaks
