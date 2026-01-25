# Sprint: auto-registration - Automatic Module Discovery and Registration
Generated: 2026-01-24
Confidence: HIGH: 2, MEDIUM: 1, LOW: 0
Status: PARTIALLY READY

## Sprint Goal
New modules in reloadable directories are automatically discovered and registered for hot-reload, eliminating manual `_RELOAD_ORDER` maintenance.

## Scope
**Deliverables:**
- Automatic discovery of reloadable modules
- Computed dependency ordering from imports
- Minimal manual configuration (only stable boundaries need declaration)

## Work Items

### P0: Implement Module Discovery
**Confidence: HIGH**

Automatically find all Python modules in reloadable directories.

**Acceptance Criteria:**
- [ ] Discovers all `.py` files in `src/cc_dump/` and `src/cc_dump/tui/`
- [ ] Excludes files in `_STABLE_BOUNDARY` set (proxy.py, cli.py, hot_reload.py, app.py)
- [ ] Excludes `__init__.py` and `__main__.py`
- [ ] Returns module names in `cc_dump.module` format
- [ ] Handles new files appearing at runtime

**Technical Notes:**
- Replace hardcoded `_RELOAD_ORDER` with dynamic discovery
- Keep `_EXCLUDED_FILES` and `_EXCLUDED_MODULES` as opt-out mechanism
- Discovery runs once per check cycle, not on every event

### P1: Implement Dependency-Ordered Reload
**Confidence: HIGH**

Compute reload order from actual import statements.

**Acceptance Criteria:**
- [ ] Parses imports from each discovered module
- [ ] Builds dependency graph (module → modules it imports)
- [ ] Topologically sorts for correct reload order
- [ ] Handles circular imports gracefully (error, not crash)
- [ ] Caches dependency graph, invalidates on file change

**Technical Notes:**
- Use `ast.parse()` to extract imports without executing code
- Only track internal `cc_dump.*` imports
- If circular dependency detected, log warning and use alphabetical order

### P2: Handle Dynamic Module Addition
**Confidence: MEDIUM**

Support adding new reloadable modules without restart.

**Acceptance Criteria:**
- [ ] New `.py` file in watched directory is detected
- [ ] New module is imported and added to reload pool
- [ ] Dependency order is recomputed
- [ ] Module is available to other reloadable code on next reload

**Technical Notes:**
- Need to handle `importlib.import_module()` for new modules
- New modules won't be in `sys.modules` yet
- Consider race condition: file created but not fully written

#### Unknowns to Resolve
- Should new modules auto-import, or only on next reload cycle?
- How to handle partial file writes during development?

#### Exit Criteria
- Tested by creating a new `.py` file while app is running
- Verified new module is reloaded on change

## Dependencies
- Sprint 1 (protocol-definition) - Protocols must exist first

## Risks
- **Import parsing complexity**: AST parsing is straightforward, but edge cases exist
- **Circular imports**: Real codebase may have subtle cycles
- **Performance**: Parsing all files on every check could be slow

## Mitigations
- Cache parsed imports, only reparse changed files
- Log dependency graph on first run for debugging
- Add timeout to parsing (shouldn't take >100ms)
