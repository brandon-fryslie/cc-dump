# Sprint: debug-panel — Debug Settings Panel

Generated: 2026-02-27T23:55Z
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal

Add a `D` (Shift+D) keybinding that opens a debug settings panel exposing three existing debug mechanisms that are currently only controllable via environment variables.

## Scope

**Deliverables:**
1. `debug_settings_panel.py` — new reloadable TUI panel (follows `settings_panel.py` pattern)
2. Runtime wiring for three toggles: log level, perf logging, memory snapshots
3. Keybinding `D` in NORMAL mode → `toggle_debug_settings` action

## Work Items

### P0: Debug settings panel widget

**Acceptance Criteria:**
- [ ] Panel opens on `D`, closes on `Esc` or `D` again
- [ ] Panel docks right, same CSS pattern as SettingsPanel
- [ ] Three controls:
  - **Log Level** — Select widget: DEBUG / INFO / WARNING / ERROR. Default: current level from `logging_setup.get_runtime()`. On change: calls `logging.getLogger("cc_dump").setLevel(level)` immediately (no save/cancel flow — changes are live).
  - **Perf Logging** — ToggleChip: ON/OFF. Default: ON. On toggle: sets a module-level `_enabled` flag in `perf_logging.py` that `monitor_slow_path` checks as an early return.
  - **Memory Snapshots** — ToggleChip: ON/OFF. Default: current `app._memory_snapshot_enabled`. On toggle: sets `app._memory_snapshot_enabled` and starts/stops `tracemalloc` as the existing code does in `__init__`.

**Technical Notes:**
- Follow SettingsPanel's mount/remove pattern (not show/hide) — see `toggle_keys` for simplest example
- Changes are live (no Saved/Cancelled message flow). This is a debug tool, not a settings form.
- These are session-only — no disk persistence (unlike SettingsPanel which writes settings.json)
- Panel is RELOADABLE — add to `_RELOAD_ORDER` in `hot_reload.py`

### P1: Keybinding and action wiring

**Acceptance Criteria:**
- [ ] `D` in NORMAL mode maps to `toggle_debug_settings` in `input_modes.py`
- [ ] `action_toggle_debug_settings` in `app.py` delegates to `action_handlers.py`
- [ ] `toggle_debug_settings` in `action_handlers.py` follows `toggle_keys` pattern (mount/remove)
- [ ] `D` appears in KEY_GROUPS under "Other" in `input_modes.py`
- [ ] `D` appears in FOOTER_KEYS for NORMAL mode

### P2: Perf logging enable/disable gate

**Acceptance Criteria:**
- [ ] `perf_logging.py` gains a module-level `_enabled = True` flag
- [ ] `monitor_slow_path` returns immediately (no-op) when `_enabled is False`
- [ ] Public `set_enabled(val: bool)` and `is_enabled() -> bool` accessors

## Dependencies

- None — all mechanisms already exist, this just wires them to the TUI

## Files Modified

| File | Change |
|------|--------|
| `src/cc_dump/tui/debug_settings_panel.py` | **NEW** — panel widget |
| `src/cc_dump/io/perf_logging.py` | Add `_enabled` flag + gate in `monitor_slow_path` |
| `src/cc_dump/tui/input_modes.py` | Add `D` keybinding + footer + KEY_GROUPS |
| `src/cc_dump/tui/action_handlers.py` | Add `toggle_debug_settings` |
| `src/cc_dump/tui/app.py` | Add `action_toggle_debug_settings` |
| `src/cc_dump/app/hot_reload.py` | Add `debug_settings_panel` to `_RELOAD_ORDER` |
