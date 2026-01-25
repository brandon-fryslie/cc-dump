# Implementation Context: verification

## Key Files

### To Create
- `tests/test_hot_reload.py` - Main test file

### To Modify
- `src/cc_dump/tui/protocols.py` - Add validate function (from Sprint 1)

### Reference
- `src/cc_dump/hot_reload.py` - System under test
- `src/cc_dump/tui/widget_factory.py` - Widgets to validate

## Test Patterns

### Module Discovery Test
```python
def test_discovers_all_reloadable_modules():
    """Discovery finds all expected reloadable modules."""
    import cc_dump.hot_reload as hr

    hr.init(str(Path(__file__).parent.parent / "src" / "cc_dump"))
    modules = hr._discover_modules()

    expected = {
        "cc_dump.colors",
        "cc_dump.analysis",
        "cc_dump.formatting",
        "cc_dump.tui.rendering",
        "cc_dump.tui.panel_renderers",
        "cc_dump.tui.event_handlers",
        "cc_dump.tui.widget_factory",
        "cc_dump.tui.protocols",
    }

    assert expected <= modules, f"Missing: {expected - modules}"

def test_excludes_stable_boundaries():
    """Discovery excludes stable boundary modules."""
    import cc_dump.hot_reload as hr

    hr.init(str(Path(__file__).parent.parent / "src" / "cc_dump"))
    modules = hr._discover_modules()

    forbidden = {"cc_dump.proxy", "cc_dump.cli", "cc_dump.hot_reload", "cc_dump.tui.app"}

    assert not (forbidden & modules), f"Found forbidden: {forbidden & modules}"
```

### Import Validation Test
```python
def test_import_validation_catches_violations():
    """Import checker catches 'from module import X' patterns."""
    # Create a temporary file with violation
    code = '''
from cc_dump.formatting import format_request
    '''
    violations = check_imports_in_code(code, {"cc_dump.formatting"})
    assert len(violations) == 1
    assert "from cc_dump.formatting import" in violations[0]

def test_import_validation_allows_module_import():
    """Import checker allows 'import module' patterns."""
    code = '''
import cc_dump.formatting
    '''
    violations = check_imports_in_code(code, {"cc_dump.formatting"})
    assert len(violations) == 0
```

### Widget Protocol Test
```python
def test_all_widgets_implement_protocol():
    """All widget classes implement HotSwappableWidget protocol."""
    from cc_dump.tui.widget_factory import (
        ConversationView,
        StatsPanel,
        TimelinePanel,
        ToolEconomicsPanel,
    )
    from cc_dump.tui.protocols import validate_widget_protocol

    widgets = [
        ConversationView(),
        StatsPanel(),
        TimelinePanel(),
        ToolEconomicsPanel(),
    ]

    for widget in widgets:
        # Should not raise
        validate_widget_protocol(widget)
```

### State Preservation Test
```python
def test_widget_state_roundtrip():
    """Widget state survives get_state/restore_state cycle."""
    from cc_dump.tui.widget_factory import StatsPanel

    # Create widget with state
    widget = StatsPanel()
    widget.update_stats(requests=10, input_tokens=1000, output_tokens=500)
    widget.models_seen.add("claude-3")

    # Extract state
    state = widget.get_state()

    # Create new widget and restore
    new_widget = StatsPanel()
    new_widget.restore_state(state)

    # Verify state preserved
    assert new_widget.request_count == 10
    assert new_widget.input_tokens == 1000
    assert new_widget.output_tokens == 500
    assert "claude-3" in new_widget.models_seen
```

### Reload Cycle Test (Mock-based)
```python
def test_reload_cycle_without_error():
    """Full reload cycle completes without exception."""
    import cc_dump.hot_reload as hr
    import sys

    hr.init(str(Path(__file__).parent.parent / "src" / "cc_dump"))

    # Get initial module references
    initial_formatting = sys.modules.get("cc_dump.formatting")

    # Simulate file change by touching mtime cache
    for path in hr._mtimes:
        if "formatting" in path:
            hr._mtimes[path] -= 1  # Make it look older

    # Trigger reload
    reloaded = hr.check_and_get_reloaded()

    # Verify formatting was reloaded
    assert "cc_dump.formatting" in reloaded

    # Verify module reference changed
    new_formatting = sys.modules.get("cc_dump.formatting")
    # Note: id() may or may not change depending on Python internals
    # Better to check that reload happened without error
```

## Pytest Fixtures
```python
@pytest.fixture
def hot_reload_init():
    """Initialize hot-reload for testing."""
    import cc_dump.hot_reload as hr
    package_dir = Path(__file__).parent.parent / "src" / "cc_dump"
    hr.init(str(package_dir))
    yield hr
    # Cleanup if needed
```
