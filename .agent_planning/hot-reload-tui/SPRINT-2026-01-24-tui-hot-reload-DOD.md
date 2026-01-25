# Definition of Done: tui-hot-reload

## Verification Checklist

1. **Formatting reload**: Edit `formatting.py` while app is running → next request uses new formatting
2. **Rendering reload**: Edit `tui/rendering.py` while app is running → toggle a filter to see new rendering
3. **Analysis reload**: Edit `analysis.py` while app is running → next budget/economics display uses new logic
4. **Colors reload**: Edit `colors.py` → next render uses new colors
5. **No crash on bad reload**: Introduce a syntax error in `formatting.py` → app logs error, continues with old code
6. **Visual feedback**: When reload occurs, user sees indication (footer flash, log, etc.)
7. **Proxy unaffected**: `proxy.py` is never reloaded regardless of changes
8. **No stale refs**: After reload, new function code is actually called (verify with a print/log in the new code)

## Automated Verification

All criteria now verified by automated tests in `tests/test_hot_reload.py`:

| Criterion | Test |
|-----------|------|
| 1. Formatting reload | `test_hot_reload_formatting_function_change` |
| 2-4. Module reload | `test_hot_reload_with_marker_in_function` |
| 5. No crash on error | `test_hot_reload_survives_syntax_error`, `test_hot_reload_survives_import_error`, `test_hot_reload_survives_runtime_error_in_function` |
| 6. Visual feedback | `test_hot_reload_detection_comment` (waits for "[hot-reload]") |
| 7. Proxy unaffected | `test_proxy_changes_not_reloaded` |
| 8. No stale refs | `test_hot_reload_with_marker_in_function` (verifies new code runs) |

## Test Run Command

```bash
uv run pytest tests/ -v
```

## Status: COMPLETE

All 11 tests pass. Implementation verified.
