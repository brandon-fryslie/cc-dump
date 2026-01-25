# Sprint: remove-legacy-mode - Remove --no-tui Legacy Mode
Generated: 2026-01-24
Confidence: HIGH: 4, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Remove the --no-tui flag, legacy consumer loop, and all dead code only used by that path. TUI becomes the sole mode.

## Scope
**Deliverables:**
- Delete `display.py` (legacy terminal facade)
- Delete `formatting_ansi.py` (ANSI rendering for legacy mode)
- Remove `--no-tui` argument and legacy code path from `cli.py`
- Remove dead hot-reload code that only served legacy mode

## Work Items

### P0: Remove --no-tui argument and legacy code path from cli.py
**Acceptance Criteria:**
- [ ] `--no-tui` argument removed from argparse
- [ ] Legacy consumer loop (the `if args.no_tui:` branch) deleted
- [ ] Legacy startup print statements deleted
- [ ] Legacy `state` dict removed (TUI manages its own state via `CcDumpApp`)
- [ ] Imports of `cc_dump.display`, `cc_dump.formatting_ansi` removed from cli.py
- [ ] The `_check_reload()` function and `_mtimes`/`_pkg_dir` globals removed (will be reimplemented properly in sprint 2)
- [ ] ANSI escape constants (RESET, BOLD, CYAN, DIM) removed from cli.py (only used for legacy prints)
- [ ] `cc_dump.colors` import removed from cli.py (only used by legacy reload)

### P1: Delete display.py
**Acceptance Criteria:**
- [ ] `src/cc_dump/display.py` deleted
- [ ] No remaining imports of `cc_dump.display` anywhere in the codebase

### P2: Delete formatting_ansi.py
**Acceptance Criteria:**
- [ ] `src/cc_dump/formatting_ansi.py` deleted
- [ ] No remaining imports of `cc_dump.formatting_ansi` anywhere in the codebase
- [ ] Comment in `formatting.py` referencing `formatting_ansi.py` updated/removed

### P3: Verify clean state
**Acceptance Criteria:**
- [ ] `just run` starts the TUI cleanly (no import errors)
- [ ] `just lint` passes
- [ ] No references to `no_tui`, `no-tui`, `display.py`, or `formatting_ansi` remain in source
- [ ] `cc-dump --help` no longer shows `--no-tui` option

## Dependencies
None — first sprint.

## Risks
- **None significant**: The legacy code path is completely separate from the TUI path. Removing it has zero impact on TUI functionality.
