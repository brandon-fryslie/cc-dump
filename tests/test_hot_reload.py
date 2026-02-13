"""Tests for cc-dump hot-reload functionality.

These tests verify that the hot-reload system correctly detects changes to
source files and reloads modules without crashing the TUI.
"""

import ast
import time
from pathlib import Path

import pytest

from tests.conftest import modify_file, settle

pytestmark = pytest.mark.pty


class TestHotReloadBasics:
    """Test basic hot-reload functionality."""

    def test_tui_starts_successfully(self, start_cc_dump):
        """Verify that cc-dump TUI starts and displays the header."""
        proc = start_cc_dump()

        assert proc.is_alive(), "cc-dump process should be running"

        content = proc.get_content()
        assert "cc-dump" in content or "Quit" in content or "headers" in content, \
            f"Expected TUI elements in output. Got:\n{content}"

    def test_hot_reload_detection_comment(self, start_cc_dump, formatting_py):
        """Test that hot-reload detects a simple modification (added comment)."""
        proc = start_cc_dump()

        with modify_file(formatting_py, lambda content: f"# Hot-reload test comment\n{content}"):
            # Hot-reload check every ~1s when idle + margin
            time.sleep(1.5)
            assert proc.is_alive(), "Process should still be alive after hot-reload"

        time.sleep(0.5)
        assert proc.is_alive(), "Process should remain alive after file restoration"


class TestHotReloadWithCodeChanges:
    """Test hot-reload when actual code changes are made."""

    def test_hot_reload_with_marker_in_function(self, start_cc_dump, formatting_py):
        """Test that hot-reloaded code actually executes (add marker to output)."""
        proc = start_cc_dump()

        marker = "HOTRELOAD_MARKER_12345"

        def add_marker(content):
            if 'def _get_timestamp():' in content:
                return content.replace(
                    'def _get_timestamp():\n    return datetime.now()',
                    f'def _get_timestamp():\n    # {marker}\n    return datetime.now()'
                )
            return content

        with modify_file(formatting_py, add_marker):
            time.sleep(1.5)
            assert proc.is_alive(), "Process should still be alive after code change"

        time.sleep(0.5)
        assert proc.is_alive(), "Process should remain alive after marker removal"

    def test_hot_reload_formatting_function_change(self, start_cc_dump, formatting_py):
        """Test that changes to formatting functions are reloaded."""
        proc = start_cc_dump()

        def modify_separator(content):
            return content.replace(
                'style: str = "heavy"  # "heavy" or "thin"',
                'style: str = "heavy"  # "heavy" or "thin" [MODIFIED]'
            )

        with modify_file(formatting_py, modify_separator):
            time.sleep(1.5)
            assert proc.is_alive(), "Process should survive formatting function changes"

        time.sleep(0.5)
        assert proc.is_alive(), "Process should remain stable after changes reverted"


class TestHotReloadErrorResilience:
    """Test that hot-reload handles errors gracefully."""

    def test_hot_reload_survives_syntax_error(self, start_cc_dump, formatting_py):
        """Test that app doesn't crash when a syntax error is introduced."""
        proc = start_cc_dump()

        def add_syntax_error(content):
            return f"this is not valid python syntax !!!\n{content}"

        with modify_file(formatting_py, add_syntax_error):
            time.sleep(1.5)
            assert proc.is_alive(), "Process should survive syntax errors in hot-reload"

            content = proc.get_content()
            assert len(content) > 0, "TUI should still be displaying content"

        time.sleep(0.5)
        assert proc.is_alive(), "Process should recover after syntax error is fixed"

    def test_hot_reload_survives_import_error(self, start_cc_dump, formatting_py):
        """Test that app doesn't crash when an import error is introduced."""
        proc = start_cc_dump()

        def add_import_error(content):
            return f"import this_module_does_not_exist_xyz\n{content}"

        with modify_file(formatting_py, add_import_error):
            time.sleep(2.0)
            assert proc.is_alive(), "Process should survive import errors in hot-reload"

        time.sleep(1.0)
        assert proc.is_alive(), "Process should recover after import error is fixed"

    def test_hot_reload_survives_runtime_error_in_function(self, start_cc_dump, formatting_py):
        """Test that introducing a runtime error doesn't crash during reload."""
        proc = start_cc_dump()

        def add_runtime_error(content):
            return content.replace(
                'def _get_timestamp():',
                'def _get_timestamp():\n    x = 1 / 0  # This will fail if called\n    return "error"\n\ndef _get_timestamp_backup():'
            )

        with modify_file(formatting_py, add_runtime_error):
            time.sleep(1.5)
            assert proc.is_alive(), "Process should survive reload with runtime error in code"

        time.sleep(0.5)
        assert proc.is_alive(), "Process should remain alive after reverting runtime error"


class TestHotReloadExclusions:
    """Test that excluded files are not hot-reloaded."""

    def test_proxy_changes_not_reloaded(self, start_cc_dump, proxy_py):
        """Test that changes to proxy.py do NOT trigger hot-reload."""
        proc = start_cc_dump()

        with modify_file(proxy_py, lambda content: f"# Test comment in proxy\n{content}"):
            time.sleep(2)
            assert proc.is_alive(), "Process should be running"

        time.sleep(0.5)
        assert proc.is_alive(), "Process should remain stable"


class TestHotReloadMultipleChanges:
    """Test hot-reload with multiple file changes."""

    def test_hot_reload_multiple_modifications(self, start_cc_dump, formatting_py):
        """Test that hot-reload handles multiple successive changes."""
        proc = start_cc_dump()

        with modify_file(formatting_py, lambda c: f"# First comment\n{c}"):
            time.sleep(1.5)
            assert proc.is_alive(), "Process should survive first modification"

        time.sleep(0.5)

        with modify_file(formatting_py, lambda c: f"# Second comment\n{c}"):
            time.sleep(1.5)
            assert proc.is_alive(), "Process should survive second modification"

        time.sleep(0.5)
        assert proc.is_alive(), "Process should remain stable after all changes"

    def test_hot_reload_rapid_changes(self, start_cc_dump, formatting_py):
        """Test that rapid successive changes don't cause issues."""
        proc = start_cc_dump()

        for i in range(3):
            with modify_file(formatting_py, lambda c: f"# Rapid change {i}\n{c}"):
                time.sleep(0.3)

        time.sleep(2)
        assert proc.is_alive(), "Process should survive rapid changes"


class TestHotReloadStability:
    """Test hot-reload stability over time."""

    def test_hot_reload_extended_operation(self, start_cc_dump, formatting_py):
        """Test that hot-reload works correctly over extended operation."""
        proc = start_cc_dump()

        time.sleep(1)
        assert proc.is_alive(), "Process should be stable initially"

        with modify_file(formatting_py, lambda c: f"# Extended test\n{c}"):
            time.sleep(1.5)
            assert proc.is_alive(), "Process should survive hot-reload"

        time.sleep(1)
        assert proc.is_alive(), "Process should remain stable after hot-reload"

        proc.send("q", press_enter=False)
        settle(proc, 0.3)


class TestImportValidation:
    """Test import validation to prevent stale references."""

    def test_import_validation(self):
        """Validate that stable modules use module-level imports, not direct imports."""
        from cc_dump.hot_reload import _RELOAD_ORDER

        test_dir = Path(__file__).parent
        project_root = test_dir.parent
        src_dir = project_root / "src" / "cc_dump"

        stable_modules = [
            src_dir / "tui" / "app.py",
            src_dir / "proxy.py",
            src_dir / "tui" / "hot_reload_controller.py",
            src_dir / "tui" / "action_handlers.py",
            src_dir / "tui" / "search_controller.py",
            src_dir / "tui" / "theme_controller.py",
            src_dir / "tui" / "dump_export.py",
        ]

        # // [LAW:one-source-of-truth] Derive from _RELOAD_ORDER, not a separate list
        forbidden_modules = set(_RELOAD_ORDER)

        # Known-safe direct imports: class references used for query_one() that
        # are never replaced during hot-reload. Document why each is safe.
        allowed_imports = {
            ("cc_dump.tui.custom_footer", "StatusFooter"),  # footer never hot-swapped
        }

        violations = []

        for module_path in stable_modules:
            if not module_path.exists():
                continue

            with open(module_path) as f:
                try:
                    tree = ast.parse(f.read(), filename=str(module_path))
                except SyntaxError:
                    continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module in forbidden_modules:
                        imported_names = [alias.name for alias in node.names]
                        if all(
                            (node.module, name) in allowed_imports
                            for name in imported_names
                        ):
                            continue
                        violations.append(
                            f"{module_path.name}:{node.lineno}: "
                            f"from {node.module} import {', '.join(imported_names)}\n"
                            f"  -> Use 'import {node.module}' instead to avoid stale references"
                        )

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
            validate_widget_protocol(widget)

    def test_validate_widget_protocol_rejects_missing_get_state(self):
        from cc_dump.tui.protocols import validate_widget_protocol

        class InvalidWidget:
            def restore_state(self, state):
                pass

        with pytest.raises(TypeError, match="missing method 'get_state\\(\\)'"):
            validate_widget_protocol(InvalidWidget())

    def test_validate_widget_protocol_rejects_missing_restore_state(self):
        from cc_dump.tui.protocols import validate_widget_protocol

        class InvalidWidget:
            def get_state(self):
                return {}

        with pytest.raises(TypeError, match="missing method 'restore_state\\(\\)'"):
            validate_widget_protocol(InvalidWidget())

    def test_validate_widget_protocol_rejects_non_callable(self):
        from cc_dump.tui.protocols import validate_widget_protocol

        class InvalidWidget:
            get_state = "not_a_function"
            restore_state = None

        with pytest.raises(TypeError, match="not callable"):
            validate_widget_protocol(InvalidWidget())


class TestWidgetStatePreservation:
    """Unit tests for widget state get/restore cycle."""

    def test_stats_panel_state_roundtrip(self):
        from cc_dump.tui.widget_factory import StatsPanel

        widget = StatsPanel()
        widget.update_stats(requests=10, model="claude-3-opus")
        widget.models_seen.add("claude-3-sonnet")

        state = widget.get_state()

        new_widget = StatsPanel()
        new_widget.restore_state(state)

        assert new_widget.request_count == 10
        assert "claude-3-opus" in new_widget.models_seen
        assert "claude-3-sonnet" in new_widget.models_seen

    def test_conversation_view_state_roundtrip(self):
        from cc_dump.tui.widget_factory import ConversationView

        widget = ConversationView()
        widget._follow_mode = False

        state = widget.get_state()

        new_widget = ConversationView()
        new_widget.restore_state(state)

        assert new_widget._follow_mode is False

    def test_economics_panel_state_roundtrip(self):
        from cc_dump.tui.widget_factory import ToolEconomicsPanel

        widget = ToolEconomicsPanel()
        state = widget.get_state()

        new_widget = ToolEconomicsPanel()
        new_widget.restore_state(state)
        assert new_widget is not None

    def test_timeline_panel_state_roundtrip(self):
        from cc_dump.tui.widget_factory import TimelinePanel

        widget = TimelinePanel()
        state = widget.get_state()

        new_widget = TimelinePanel()
        new_widget.restore_state(state)
        assert new_widget is not None


class TestHotReloadModuleStructure:
    """Unit tests for hot-reload module configuration."""

    def test_reload_order_is_defined(self):
        from cc_dump.hot_reload import _RELOAD_ORDER

        assert isinstance(_RELOAD_ORDER, list)
        assert len(_RELOAD_ORDER) > 0

        expected_modules = [
            "cc_dump.formatting",
            "cc_dump.router",
            "cc_dump.tui.rendering",
            "cc_dump.tui.widget_factory",
        ]
        for mod in expected_modules:
            assert mod in _RELOAD_ORDER, f"Expected module {mod} in reload order"

    def test_excluded_files_contain_stable_boundaries(self):
        from cc_dump.hot_reload import _EXCLUDED_FILES

        assert isinstance(_EXCLUDED_FILES, set)

        required_exclusions = ["proxy.py", "cli.py", "hot_reload.py"]
        for exc in required_exclusions:
            assert exc in _EXCLUDED_FILES, f"Expected {exc} to be excluded"

    def test_excluded_modules_contain_live_instances(self):
        from cc_dump.hot_reload import _EXCLUDED_MODULES

        assert isinstance(_EXCLUDED_MODULES, set)

        required_exclusions = ["tui/app.py", "tui/widgets.py"]
        for exc in required_exclusions:
            assert exc in _EXCLUDED_MODULES, f"Expected {exc} to be excluded"

    def test_reload_order_respects_dependencies(self):
        from cc_dump.hot_reload import _RELOAD_ORDER

        colors_idx = _RELOAD_ORDER.index("cc_dump.colors")
        analysis_idx = _RELOAD_ORDER.index("cc_dump.analysis")
        formatting_idx = _RELOAD_ORDER.index("cc_dump.formatting")
        assert formatting_idx > colors_idx, "formatting should come after colors"
        assert formatting_idx > analysis_idx, "formatting should come after analysis"

        rendering_idx = _RELOAD_ORDER.index("cc_dump.tui.rendering")
        assert rendering_idx > formatting_idx, "rendering should come after formatting"

        widget_factory_idx = _RELOAD_ORDER.index("cc_dump.tui.widget_factory")
        assert widget_factory_idx > rendering_idx, "widget_factory should come after rendering"


class TestHotReloadFileDetection:
    """Unit tests for hot-reload file change detection."""

    def test_init_sets_watch_dirs(self):
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert len(hr._watch_dirs) > 0
        assert str(test_dir) in hr._watch_dirs

    def test_scan_mtimes_populates_cache(self):
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert len(hr._mtimes) > 0

        formatting_paths = [p for p in hr._mtimes.keys() if "formatting.py" in p]
        assert len(formatting_paths) > 0, "Should have mtime for formatting.py"

    def test_get_changed_files_returns_empty_initially(self):
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        hr._get_changed_files()
        changed = hr._get_changed_files()

        assert isinstance(changed, set)
        assert len(changed) == 0, "No files should have changed"

    def test_check_returns_false_when_no_changes(self):
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        hr.check()
        result = hr.check()

        assert result is False, "Should return False when no changes detected"

    def test_check_and_get_reloaded_returns_empty_list_when_no_changes(self):
        import cc_dump.hot_reload as hr
        from pathlib import Path

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        hr.check_and_get_reloaded()
        reloaded = hr.check_and_get_reloaded()

        assert isinstance(reloaded, list)
        assert len(reloaded) == 0, "Should return empty list when no changes"
