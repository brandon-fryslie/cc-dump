# Evaluation: Hot-Reload API Architecture Lock-In
Generated: 2026-01-24
Verdict: CONTINUE

## Topic
Lock in the hot-reload architecture with a guaranteed API surface so all future changes are hot-reloadable by default.

## Current State Analysis

### Existing Architecture

The codebase has evolved to a partial hot-reload architecture:

**Non-Reloadable (Stable Boundary):**
- `proxy.py` - HTTP handler, must stay running continuously
- `cli.py` - Entry point, initializes everything
- `hot_reload.py` - The reloader itself
- `tui/app.py` - CcDumpApp instance (Textual App lifecycle)

**Reloadable Modules (Display Path):**
- `colors.py` - Color definitions
- `analysis.py` - Token estimation, turn budgets, tool correlation
- `formatting.py` - Request/response → FormattedBlock IR
- `tui/rendering.py` - FormattedBlock → Rich renderables
- `tui/panel_renderers.py` - Panel display text generation
- `tui/event_handlers.py` - Event processing logic
- `tui/widget_factory.py` - Widget class definitions with state save/restore

**Shim Modules:**
- `tui/widgets.py` - Re-exports from widget_factory.py

### Key Patterns Established

1. **Widget Hot-Swap Pattern**: Widgets defined in `widget_factory.py` with:
   - `get_state()` - Extract serializable state
   - `restore_state(state)` - Restore from saved state
   - Factory functions `create_*()` for instantiation

2. **Event Handler Delegation**: `app.py._handle_event()` delegates to `event_handlers.py` functions

3. **Module-Level Access**: All cross-module calls use `module.function()` not `from module import function`

4. **Reload Detection**: `check_and_get_reloaded()` returns list of reloaded modules, app decides how to respond

### Gaps in Current Architecture

1. **No Formal Contract**: The hot-reload guarantees are implicit, not enforced
2. **Manual Registration**: New modules must be manually added to `_RELOAD_ORDER`
3. **No Validation**: Nothing prevents breaking changes to the stable boundary
4. **Incomplete Widget Protocol**: `get_state()`/`restore_state()` not formally documented
5. **State Schema Not Versioned**: State format changes could break hot-swap

## What Needs to Be Built

### 1. Formal API Contract Definition

Document and enforce the boundaries:
- **Stable Boundary Protocol**: What must NEVER change signatures
- **Reloadable Module Protocol**: What modules must implement
- **Widget Protocol**: Required methods for hot-swappable widgets
- **Event Protocol**: How events flow from proxy → handlers

### 2. Auto-Registration for Reloadable Modules

Instead of manual `_RELOAD_ORDER`, use a discovery mechanism:
- All modules in certain directories are automatically reloadable
- Explicit opt-out for stable boundaries
- Dependency ordering computed from imports

### 3. Widget Protocol Enforcement

Formalize the widget pattern:
- Base class or protocol for hot-swappable widgets
- Type hints for state dicts
- Validation on state restore

### 4. Verification Tools

Add development-time checks:
- Lint rule: No `from reloadable_module import X` in stable modules
- Test: All widgets implement get_state/restore_state
- Test: All reloadable modules can be reloaded without error

## Risks

1. **Over-Engineering**: Too much ceremony could slow development
2. **Protocol Drift**: Formal contract but no enforcement = false confidence
3. **State Compatibility**: Widget state changes between versions

## Recommendation

Proceed with a minimal viable contract:
1. Document the architecture (HOT_RELOAD_ARCHITECTURE.md)
2. Add a base protocol/ABC for widgets
3. Auto-register TUI modules for reload
4. Add a single test that exercises hot-reload

This balances formality with practicality.
