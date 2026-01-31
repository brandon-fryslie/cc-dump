# Evaluation: Hot Reload Widget Replacement Failures

Generated: 2026-01-30

## Verdict: CONTINUE

## Problem Statement

Hot reloading triggers `NoMatches` errors when querying widgets by ID after `_replace_all_widgets()` runs. The user sees:

```
NoMatches: No nodes match '#conversation-view' on Screen(id='_default')
```

Traceback shows: keypress → reactive watcher → `_rerender_if_mounted()` → `_get_conv()` → `query_one("#conversation-view")` → NoMatches.

## Root Cause Analysis

### Primary Bug: Non-atomic widget replacement

`_replace_all_widgets()` in `app.py:222-286` has a critical atomicity failure:

1. **Lines 271-275**: Old widgets are removed (`old_conv.remove()`, etc.)
2. **Lines 246-268**: New widgets are created from reloaded factory
3. **Lines 278-282**: New widgets are mounted

**The problem**: If step 2 or 3 throws an exception (e.g., reloaded module has a bug, import error, attribute error), the old widgets are already gone. The exception is caught by the try/except in `_check_hot_reload()` (line 212-220), logged, and swallowed. The DOM is now permanently broken — all subsequent `query_one()` calls fail with `NoMatches`.

### Contributing Factor: Non-awaited async operations

Both `remove()` and `mount()` return awaitables (`AwaitRemove`, `AwaitMount`). While `mount()` does register widgets synchronously via `_register()`, `remove()` defers actual cleanup via `call_next()`. This creates timing ambiguity.

### Contributing Factor: Widget accessors have no fallback

Every widget accessor (`_get_conv()`, `_get_stats()`, etc.) uses `query_one()` which throws `NoMatches` on failure. There's no graceful degradation.

## Existing Protections (Insufficient)

- Import validation test catches `from X import Y` in stable modules ✓
- Widget protocol validation test ✓
- Error handling in `_check_hot_reload` catches exceptions ✗ (catches but doesn't recover DOM)
- `_rerender_if_mounted` checks `is_running` ✗ (doesn't check widget existence)

## Impact

Any error during hot reload permanently breaks the TUI until restart. This makes the hot reload feature unreliable for its primary use case (iterating on rendering/formatting code).
