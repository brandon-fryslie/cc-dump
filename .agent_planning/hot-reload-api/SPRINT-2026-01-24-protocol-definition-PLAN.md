# Sprint: protocol-definition - Define Hot-Reload Protocols and Boundaries
Generated: 2026-01-24
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Establish formal protocols that guarantee any code following them is hot-reloadable without proxy restart.

## Scope
**Deliverables:**
- `HotSwappableWidget` protocol/ABC defining required methods
- Architecture documentation with clear boundaries
- Import validation to prevent stale references

## Work Items

### P0: Create HotSwappableWidget Protocol
**Confidence: HIGH**

Define a formal protocol that all hot-swappable widgets must implement.

**Acceptance Criteria:**
- [ ] Protocol defines `get_state() -> dict` method signature
- [ ] Protocol defines `restore_state(state: dict) -> None` method signature
- [ ] All existing widgets (ConversationView, StatsPanel, TimelinePanel, ToolEconomicsPanel) implement the protocol
- [ ] Factory functions typed to return protocol-compliant widgets
- [ ] Type checker can verify protocol compliance

**Technical Notes:**
- Use `typing.Protocol` for structural subtyping (duck typing with type safety)
- Keep protocol minimal - only state transfer methods
- Widget classes don't need to explicitly inherit (structural typing)

**Implementation:**
```python
# In tui/protocols.py (new file, reloadable)
from typing import Protocol, Dict, Any

class HotSwappableWidget(Protocol):
    """Protocol for widgets that can be hot-swapped at runtime."""

    def get_state(self) -> Dict[str, Any]:
        """Extract widget state for transfer to a new instance."""
        ...

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from a previous instance."""
        ...
```

### P1: Create Architecture Documentation
**Confidence: HIGH**

Document the hot-reload architecture as a developer reference.

**Acceptance Criteria:**
- [ ] HOT_RELOAD_ARCHITECTURE.md exists in project root or docs/
- [ ] Documents the three module categories (Stable, Reloadable, Shim)
- [ ] Lists each module and its category
- [ ] Explains the widget hot-swap pattern with code examples
- [ ] Explains module-level import requirement
- [ ] Includes "How to add a new reloadable module" section
- [ ] Includes "How to add a new widget" section

**Technical Notes:**
- Keep it practical, not academic
- Include copy-paste templates
- Reference specific files

### P2: Add Import Validation Helper
**Confidence: HIGH**

Provide a way to validate import patterns at development time.

**Acceptance Criteria:**
- [ ] Script or test that checks for `from reloadable import func` patterns in stable modules
- [ ] Validates that stable modules only use `import module` style
- [ ] Can be run as part of test suite or pre-commit
- [ ] Reports violations with file:line and suggested fix

**Technical Notes:**
- Use AST parsing for reliability
- Focus on catching the common mistake: `from cc_dump.formatting import format_request`
- Only check stable boundary files (app.py currently)

## Dependencies
- None - this is foundational work

## Risks
- **Over-specification**: Keep protocols minimal
- **Stale docs**: Link docs to code so they stay in sync
