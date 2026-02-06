# Sprint 1: rename-package - Rename cc-dump to surview
Generated: 2026-02-06
Confidence: HIGH: 4, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Rename the Python package from cc_dump to surview, update all references, remove tiktoken dependency. Purely mechanical; no behavioral changes.

## Scope
**Deliverables:**
- Package directory renamed
- All imports updated
- Build/tooling config updated
- Class names and log messages updated

## Work Items

### P0: Rename package directory and update pyproject.toml
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `src/cc_dump/` renamed to `src/surview/` via `git mv`
- [ ] pyproject.toml: name="surview", description="HTTP debugging proxy with TUI"
- [ ] pyproject.toml: scripts `surview = "surview.cli:main"`
- [ ] pyproject.toml: packages=["src/surview"]
- [ ] pyproject.toml: tiktoken removed from dependencies
- [ ] pyproject.toml: keywords updated for generic HTTP debugging
- [ ] pyproject.toml: URLs updated

**Technical Notes:**
- `git mv src/cc_dump src/surview` for clean history
- Remove `"tiktoken>=0.5.0"` from dependencies list

### P1: Update all Python imports
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Every `import cc_dump` → `import surview` across all .py files in src/ and tests/
- [ ] Every `from cc_dump` → `from surview` across all .py files
- [ ] String literals "cc_dump" → "surview" in hot_reload.py (_RELOAD_ORDER, _RELOAD_IF_CHANGED)
- [ ] String literal "cc-dump" → "surview" in har_recorder.py (HAR creator name)
- [ ] Path constants "cc-dump" → "surview" in sessions.py, cli.py, conftest.py
- [ ] `uv run pytest` passes after rename

**Technical Notes:**
- Maintain the stable-boundary import pattern: `import surview.module` (never `from surview.module import func`) in proxy.py, cli.py, tui/app.py, tui/widgets.py, hot_reload.py, har_recorder.py, har_replayer.py, sessions.py
- Reloadable modules can use either pattern

### P2: Update justfile and class names
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] justfile: `uv run cc-dump` → `uv run surview`, uninstall/module refs updated
- [ ] `CcDumpApp` → `SurviewApp` in tui/app.py
- [ ] Log messages "cc-dump" → "surview" in tui/app.py and cli.py

### P3: Update documentation references
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] CLAUDE.md: all cc-dump / cc_dump references updated
- [ ] ARCHITECTURE.md: references updated (if exists)
- [ ] PROJECT_SPEC.md: references updated (if exists)

## Dependencies
- None (first sprint)

## Risks
- **Import breakage**: Low risk — mechanical find/replace, verified by test suite
