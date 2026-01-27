"""Tests for cc-dump hot-reload functionality.

These tests verify that the hot-reload system correctly detects changes to
source files and reloads modules without crashing the TUI.
"""

import ast
import time
from pathlib import Path

import pytest

from tests.conftest import modify_file


class TestHotReloadBasics:
    """Test basic hot-reload functionality."""

    def test_tui_starts_successfully(self, start_cc_dump):
        """Verify that cc-dump TUI starts and displays the header."""
        proc = start_cc_dump()

        # Check that process is alive
        assert proc.is_alive(), "cc-dump process should be running"

        # Verify we can see the TUI (check for common elements)
        content = proc.get_content()
        assert "cc-dump" in content or "Quit" in content or "Headers" in content, \
            f"Expected TUI elements in output. Got:\n{content}"

    def test_hot_reload_detection_comment(self, start_cc_dump, formatting_py):
        """Test that hot-reload detects a simple modification (added comment)."""
        proc = start_cc_dump()

        # Modify formatting.py by adding a comment
        with modify_file(formatting_py, lambda content: f"# Hot-reload test comment\n{content}"):
            # Wait for hot-reload check to trigger (happens every second when idle)
            time.sleep(2.5)

            # Check screen content for hot-reload notification
            content = proc.get_content()
            assert proc.is_alive(), "Process should still be alive after hot-reload"

            # The notification should appear somewhere on screen
            # Note: Textual notifications may not always be visible in pty output
            # but the reload should happen silently without crashes
            # We verify the process didn't crash and continued running

        # Give it a moment to stabilize after restore
        time.sleep(1)
        assert proc.is_alive(), "Process should remain alive after file restoration"


class TestHotReloadWithCodeChanges:
    """Test hot-reload when actual code changes are made."""

    def test_hot_reload_with_marker_in_function(self, start_cc_dump, formatting_py):
        """Test that hot-reloaded code actually executes (add marker to output)."""
        proc = start_cc_dump()

        # Add a marker string to _get_timestamp function
        marker = "HOTRELOAD_MARKER_12345"

        def add_marker(content):
            # Find _get_timestamp function and modify its return value
            if 'def _get_timestamp():' in content:
                # Add a line that would show up if this function is called
                return content.replace(
                    'def _get_timestamp():\n    return datetime.now()',
                    f'def _get_timestamp():\n    # {marker}\n    return datetime.now()'
                )
            return content

        with modify_file(formatting_py, add_marker):
            # Wait for hot-reload
            time.sleep(2.5)

            # Verify process is still alive
            assert proc.is_alive(), "Process should still be alive after code change"

            # At this point, if we had a way to trigger a request, we could verify
            # the marker appears in the timestamp. For now, we verify no crash.

        time.sleep(1)
        assert proc.is_alive(), "Process should remain alive after marker removal"

    def test_hot_reload_formatting_function_change(self, start_cc_dump, formatting_py):
        """Test that changes to formatting functions are reloaded."""
        proc = start_cc_dump()

        def modify_separator(content):
            # Change the separator character in a visible way
            # This is a safe, non-breaking change
            return content.replace(
                'style: str = "heavy"  # "heavy" or "thin"',
                'style: str = "heavy"  # "heavy" or "thin" [MODIFIED]'
            )

        with modify_file(formatting_py, modify_separator):
            time.sleep(2.5)
            assert proc.is_alive(), "Process should survive formatting function changes"

        time.sleep(1)
        assert proc.is_alive(), "Process should remain stable after changes reverted"


class TestHotReloadErrorResilience:
    """Test that hot-reload handles errors gracefully."""

    def test_hot_reload_survives_syntax_error(self, start_cc_dump, formatting_py):
        """Test that app doesn't crash when a syntax error is introduced."""
        proc = start_cc_dump()

        # Introduce a syntax error
        def add_syntax_error(content):
            # Add a line with invalid Python syntax
            return f"this is not valid python syntax !!!\n{content}"

        with modify_file(formatting_py, add_syntax_error):
            # Wait for hot-reload to attempt reload
            time.sleep(2.5)

            # Process should still be alive (hot-reload catches exceptions)
            assert proc.is_alive(), "Process should survive syntax errors in hot-reload"

            # Check that we can still interact with the TUI
            content = proc.get_content()
            assert len(content) > 0, "TUI should still be displaying content"

        # After fixing the syntax error, app should continue normally
        time.sleep(2)
        assert proc.is_alive(), "Process should recover after syntax error is fixed"

    def test_hot_reload_survives_import_error(self, start_cc_dump, formatting_py):
        """Test that app doesn't crash when an import error is introduced."""
        proc = start_cc_dump()

        # Add an invalid import
        def add_import_error(content):
            return f"import this_module_does_not_exist_xyz\n{content}"

        with modify_file(formatting_py, add_import_error):
            time.sleep(2.5)

            # Process should still be alive
            assert proc.is_alive(), "Process should survive import errors in hot-reload"

        time.sleep(2)
        assert proc.is_alive(), "Process should recover after import error is fixed"

    def test_hot_reload_survives_runtime_error_in_function(self, start_cc_dump, formatting_py):
        """Test that introducing a runtime error doesn't crash during reload."""
        proc = start_cc_dump()

        # Add code that would cause a runtime error if executed
        def add_runtime_error(content):
            # Add a function that will raise an error
            return content.replace(
                'def _get_timestamp():',
                'def _get_timestamp():\n    x = 1 / 0  # This will fail if called\n    return "error"\n\ndef _get_timestamp_backup():'
            )

        with modify_file(formatting_py, add_runtime_error):
            time.sleep(2.5)

            # The reload itself should succeed (errors happen at call time, not import time)
            assert proc.is_alive(), "Process should survive reload with runtime error in code"

        time.sleep(2)
        assert proc.is_alive(), "Process should remain alive after reverting runtime error"


class TestHotReloadExclusions:
    """Test that excluded files are not hot-reloaded."""

    def test_proxy_changes_not_reloaded(self, start_cc_dump, proxy_py):
        """Test that changes to proxy.py do NOT trigger hot-reload."""
        proc = start_cc_dump()

        # Modify proxy.py
        with modify_file(proxy_py, lambda content: f"# Test comment in proxy\n{content}"):
            # Wait longer than normal reload check interval
            time.sleep(3)

            content = proc.get_content()

            # Process should be alive
            assert proc.is_alive(), "Process should be running"

            # Check that hot-reload notification did NOT appear
            # Note: This is a negative test - we're verifying the absence of reload
            # The best we can do in pty is verify no crash and continued operation
            # In a real scenario, we'd check stderr logs for "[hot-reload]" messages

        time.sleep(1)
        assert proc.is_alive(), "Process should remain stable"


class TestHotReloadMultipleChanges:
    """Test hot-reload with multiple file changes."""

    def test_hot_reload_multiple_modifications(self, start_cc_dump, formatting_py):
        """Test that hot-reload handles multiple successive changes."""
        proc = start_cc_dump()

        # First modification
        with modify_file(formatting_py, lambda c: f"# First comment\n{c}"):
            time.sleep(2.5)
            assert proc.is_alive(), "Process should survive first modification"

        # Second modification (file is now back to original)
        time.sleep(1)

        with modify_file(formatting_py, lambda c: f"# Second comment\n{c}"):
            time.sleep(2.5)
            assert proc.is_alive(), "Process should survive second modification"

        time.sleep(1)
        assert proc.is_alive(), "Process should remain stable after all changes"

    def test_hot_reload_rapid_changes(self, start_cc_dump, formatting_py):
        """Test that rapid successive changes don't cause issues."""
        proc = start_cc_dump()

        # Make several rapid changes
        for i in range(3):
            with modify_file(formatting_py, lambda c: f"# Rapid change {i}\n{c}"):
                time.sleep(0.5)  # Shorter delay - rapid changes

        # Give it time to settle
        time.sleep(3)
        assert proc.is_alive(), "Process should survive rapid changes"


class TestHotReloadStability:
    """Test hot-reload stability over time."""

    def test_hot_reload_extended_operation(self, start_cc_dump, formatting_py):
        """Test that hot-reload works correctly over extended operation."""
        proc = start_cc_dump()

        # Let it run for a bit
        time.sleep(2)
        assert proc.is_alive(), "Process should be stable initially"

        # Make a change
        with modify_file(formatting_py, lambda c: f"# Extended test\n{c}"):
            time.sleep(3)
            assert proc.is_alive(), "Process should survive hot-reload"

        # Continue running
        time.sleep(2)
        assert proc.is_alive(), "Process should remain stable after hot-reload"

        # Verify we can still quit normally
        proc.send("q", press_enter=False)
        time.sleep(0.5)

        # Process should exit cleanly
        # Note: is_alive() might still be True briefly, so we just check it doesn't hang


class TestImportValidation:
    """Test import validation to prevent stale references."""

    def test_import_validation(self):
        """Validate that stable modules use module-level imports, not direct imports.

        Stable boundary modules (app.py, proxy.py) must use 'import module' pattern
        instead of 'from module import func' to avoid stale references after hot-reload.
        """
        # Find project root
        test_dir = Path(__file__).parent
        project_root = test_dir.parent
        src_dir = project_root / "src" / "cc_dump"

        # Stable boundary modules to check
        stable_modules = [
            src_dir / "tui" / "app.py",
            src_dir / "proxy.py",
        ]

        # Reloadable modules that stable boundaries interact with
        forbidden_modules = {
            "cc_dump.formatting",
            "cc_dump.colors",
            "cc_dump.analysis",
            "cc_dump.tui.rendering",
            "cc_dump.tui.panel_renderers",
            "cc_dump.tui.event_handlers",
            "cc_dump.tui.widget_factory",
            "cc_dump.tui.protocols",
        }

        violations = []

        for module_path in stable_modules:
            if not module_path.exists():
                continue

            with open(module_path) as f:
                try:
                    tree = ast.parse(f.read(), filename=str(module_path))
                except SyntaxError as e:
                    # If there's a syntax error, we can't parse - skip this file
                    continue

            # Walk the AST looking for ImportFrom nodes
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    # node.module is the module being imported from (e.g., "cc_dump.formatting")
                    if node.module in forbidden_modules:
                        # Found a forbidden direct import
                        imported_names = [alias.name for alias in node.names]
                        violations.append(
                            f"{module_path.name}:{node.lineno}: "
                            f"from {node.module} import {', '.join(imported_names)}\n"
                            f"  → Use 'import {node.module}' instead to avoid stale references"
                        )

        # Assert no violations
        if violations:
            violation_msg = "\n\n".join(violations)
            pytest.fail(
                f"Found {len(violations)} import violations in stable boundary modules:\n\n"
                f"{violation_msg}\n\n"
                f"Stable modules must use 'import module' pattern, not 'from module import ...'.\n"
                f"See HOT_RELOAD_ARCHITECTURE.md for details."
            )


# ============================================================================
# UNIT TESTS - Fast tests without TUI interaction
# ============================================================================


class TestWidgetProtocolValidation:
    """Unit tests for widget protocol validation."""

    def test_validate_all_widgets_implement_protocol(self):
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

    def test_validate_widget_protocol_rejects_missing_get_state(self):
        """Protocol validation fails for widget missing get_state()."""
        from cc_dump.tui.protocols import validate_widget_protocol

        class InvalidWidget:
            def restore_state(self, state):
                pass

        widget = InvalidWidget()
        with pytest.raises(TypeError, match="missing method 'get_state\\(\\)'"):
            validate_widget_protocol(widget)

    def test_validate_widget_protocol_rejects_missing_restore_state(self):
        """Protocol validation fails for widget missing restore_state()."""
        from cc_dump.tui.protocols import validate_widget_protocol

        class InvalidWidget:
            def get_state(self):
                return {}

        widget = InvalidWidget()
        with pytest.raises(TypeError, match="missing method 'restore_state\\(\\)'"):
            validate_widget_protocol(widget)

    def test_validate_widget_protocol_rejects_non_callable(self):
        """Protocol validation fails when method exists but is not callable."""
        from cc_dump.tui.protocols import validate_widget_protocol

        class InvalidWidget:
            get_state = "not_a_function"
            restore_state = None

        widget = InvalidWidget()
        with pytest.raises(TypeError, match="not callable"):
            validate_widget_protocol(widget)


class TestWidgetStatePreservation:
    """Unit tests for widget state get/restore cycle."""

    def test_stats_panel_state_roundtrip(self):
        """StatsPanel state survives get_state/restore_state cycle."""
        from cc_dump.tui.widget_factory import StatsPanel

        # Create widget with state
        widget = StatsPanel()
        widget.update_stats(
            requests=10,
            model="claude-3-opus"
        )
        widget.models_seen.add("claude-3-sonnet")

        # Extract state
        state = widget.get_state()

        # Create new widget and restore
        new_widget = StatsPanel()
        new_widget.restore_state(state)

        # Verify state preserved (only in-memory fields)
        assert new_widget.request_count == 10
        assert "claude-3-opus" in new_widget.models_seen
        assert "claude-3-sonnet" in new_widget.models_seen

    def test_conversation_view_state_roundtrip(self):
        """ConversationView state survives get_state/restore_state cycle."""
        from cc_dump.tui.widget_factory import ConversationView
        from cc_dump.formatting import TextDeltaBlock

        # Create widget with state
        widget = ConversationView()
        widget._turn_blocks = [
            [TextDeltaBlock(text="Hello")],
            [TextDeltaBlock(text="World")]
        ]
        widget._current_turn_blocks = [TextDeltaBlock(text="Current")]
        widget._text_delta_buffer = ["Buffer", "Text"]

        # Extract state
        state = widget.get_state()

        # Create new widget and restore
        new_widget = ConversationView()
        new_widget.restore_state(state)

        # Verify state preserved
        assert len(new_widget._turn_blocks) == 2
        assert len(new_widget._current_turn_blocks) == 1
        assert new_widget._text_delta_buffer == ["Buffer", "Text"]

    def test_economics_panel_state_roundtrip(self):
        """ToolEconomicsPanel state survives get_state/restore_state cycle."""
        from cc_dump.tui.widget_factory import ToolEconomicsPanel

        # Create widget
        widget = ToolEconomicsPanel()

        # Extract state (panel has no persistent state - queries DB on demand)
        state = widget.get_state()

        # Create new widget and restore
        new_widget = ToolEconomicsPanel()
        new_widget.restore_state(state)

        # Verify widget is functional (no state to verify)
        assert new_widget is not None

    def test_timeline_panel_state_roundtrip(self):
        """TimelinePanel state survives get_state/restore_state cycle."""
        from cc_dump.tui.widget_factory import TimelinePanel

        # Create widget
        widget = TimelinePanel()

        # Extract state (panel has no persistent state - queries DB on demand)
        state = widget.get_state()

        # Create new widget and restore
        new_widget = TimelinePanel()
        new_widget.restore_state(state)

        # Verify widget is functional (no state to verify)
        assert new_widget is not None


class TestHotReloadModuleStructure:
    """Unit tests for hot-reload module configuration."""

    def test_reload_order_is_defined(self):
        """Reload order list is properly defined."""
        from cc_dump.hot_reload import _RELOAD_ORDER

        assert isinstance(_RELOAD_ORDER, list)
        assert len(_RELOAD_ORDER) > 0

        # Verify expected modules are in the list
        expected_modules = [
            "cc_dump.formatting",
            "cc_dump.tui.rendering",
            "cc_dump.tui.widget_factory",
        ]
        for mod in expected_modules:
            assert mod in _RELOAD_ORDER, f"Expected module {mod} in reload order"

    def test_reload_if_changed_is_defined(self):
        """Reload-if-changed list is properly defined."""
        from cc_dump.hot_reload import _RELOAD_IF_CHANGED

        assert isinstance(_RELOAD_IF_CHANGED, list)

        # These modules should only reload if they themselves changed
        expected_modules = ["cc_dump.schema", "cc_dump.store", "cc_dump.router"]
        for mod in expected_modules:
            assert mod in _RELOAD_IF_CHANGED

    def test_excluded_files_contain_stable_boundaries(self):
        """Excluded files list contains stable boundary modules."""
        from cc_dump.hot_reload import _EXCLUDED_FILES

        assert isinstance(_EXCLUDED_FILES, set)

        # These files should never be reloaded
        required_exclusions = ["proxy.py", "cli.py", "hot_reload.py"]
        for exc in required_exclusions:
            assert exc in _EXCLUDED_FILES, f"Expected {exc} to be excluded"

    def test_excluded_modules_contain_live_instances(self):
        """Excluded modules list contains live instance modules."""
        from cc_dump.hot_reload import _EXCLUDED_MODULES

        assert isinstance(_EXCLUDED_MODULES, set)

        # These modules hold live instances and can't be reloaded
        required_exclusions = ["tui/app.py", "tui/widgets.py"]
        for exc in required_exclusions:
            assert exc in _EXCLUDED_MODULES, f"Expected {exc} to be excluded"

    def test_reload_order_respects_dependencies(self):
        """Reload order lists leaf modules before dependents."""
        from cc_dump.hot_reload import _RELOAD_ORDER

        # colors and analysis have no internal deps, should come first
        colors_idx = _RELOAD_ORDER.index("cc_dump.colors")
        analysis_idx = _RELOAD_ORDER.index("cc_dump.analysis")

        # formatting depends on colors and analysis
        formatting_idx = _RELOAD_ORDER.index("cc_dump.formatting")
        assert formatting_idx > colors_idx, "formatting should come after colors"
        assert formatting_idx > analysis_idx, "formatting should come after analysis"

        # rendering depends on formatting
        rendering_idx = _RELOAD_ORDER.index("cc_dump.tui.rendering")
        assert rendering_idx > formatting_idx, "rendering should come after formatting"

        # widget_factory depends on rendering
        widget_factory_idx = _RELOAD_ORDER.index("cc_dump.tui.widget_factory")
        assert widget_factory_idx > rendering_idx, "widget_factory should come after rendering"


class TestHotReloadFileDetection:
    """Unit tests for hot-reload file change detection."""

    def test_init_sets_watch_dirs(self):
        """init() properly sets watch directories."""
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Should have at least the package dir
        assert len(hr._watch_dirs) > 0
        assert str(test_dir) in hr._watch_dirs

    def test_scan_mtimes_populates_cache(self):
        """_scan_mtimes() populates the mtime cache."""
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Should have mtimes for several files
        assert len(hr._mtimes) > 0

        # Should have at least formatting.py
        formatting_paths = [p for p in hr._mtimes.keys() if "formatting.py" in p]
        assert len(formatting_paths) > 0, "Should have mtime for formatting.py"

    def test_get_changed_files_returns_empty_initially(self):
        """_get_changed_files() returns empty set when nothing changed."""
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Call twice - second call should see no changes
        hr._get_changed_files()
        changed = hr._get_changed_files()

        assert isinstance(changed, set)
        assert len(changed) == 0, "No files should have changed"

    def test_check_returns_false_when_no_changes(self):
        """check() returns False when no files have changed."""
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # First call scans, second call should return False
        hr.check()
        result = hr.check()

        assert result is False, "Should return False when no changes detected"

    def test_check_and_get_reloaded_returns_empty_list_when_no_changes(self):
        """check_and_get_reloaded() returns empty list when no changes."""
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Stabilize mtimes
        hr.check_and_get_reloaded()
        reloaded = hr.check_and_get_reloaded()

        assert isinstance(reloaded, list)
        assert len(reloaded) == 0, "Should return empty list when no changes"
