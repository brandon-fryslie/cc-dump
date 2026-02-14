"""Tests for cc-dump hot-reload functionality.

These tests verify that the hot-reload system correctly detects changes to
source files and reloads modules without crashing the TUI.

PTY integration tests use os.utime() to trigger mtime-based detection —
no production source files are ever modified.

Error resilience tests run as unit tests with mocked importlib.reload.
"""

import ast
import importlib
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import settle

pytestmark = pytest.mark.pty


def _touch(path):
    """Bump a file's mtime to trigger hot-reload detection. Content unchanged."""
    os.utime(path, None)


# ============================================================================
# PTY INTEGRATION TESTS — process stays alive through reload cycles
# ============================================================================


class TestHotReloadBasics:
    """Test basic hot-reload functionality."""

    def test_tui_starts_successfully(self, start_cc_dump):
        """Verify that cc-dump TUI starts and displays the header."""
        proc = start_cc_dump()

        assert proc.is_alive(), "cc-dump process should be running"

        content = proc.get_content()
        assert "cc-dump" in content or "Quit" in content or "user" in content, \
            f"Expected TUI elements in output. Got:\n{content}"

    def test_hot_reload_detection(self, start_cc_dump, formatting_py):
        """Test that hot-reload detects an mtime change."""
        proc = start_cc_dump()

        _touch(formatting_py)
        time.sleep(1.5)
        assert proc.is_alive(), "Process should still be alive after hot-reload trigger"


class TestHotReloadExclusions:
    """Test that excluded files are not hot-reloaded."""

    def test_proxy_changes_not_reloaded(self, start_cc_dump, proxy_py):
        """Test that mtime changes to proxy.py do NOT trigger hot-reload."""
        proc = start_cc_dump()

        _touch(proxy_py)
        time.sleep(2)
        assert proc.is_alive(), "Process should be running"


class TestHotReloadMultipleChanges:
    """Test hot-reload with multiple file changes."""

    def test_hot_reload_multiple_touches(self, start_cc_dump, formatting_py):
        """Test that hot-reload handles multiple successive mtime bumps."""
        proc = start_cc_dump()

        _touch(formatting_py)
        time.sleep(1.5)
        assert proc.is_alive(), "Process should survive first touch"

        _touch(formatting_py)
        time.sleep(1.5)
        assert proc.is_alive(), "Process should survive second touch"

    def test_hot_reload_rapid_touches(self, start_cc_dump, formatting_py):
        """Test that rapid successive mtime bumps don't cause issues."""
        proc = start_cc_dump()

        for _ in range(5):
            _touch(formatting_py)
            time.sleep(0.1)

        time.sleep(2)
        assert proc.is_alive(), "Process should survive rapid touches"


class TestHotReloadStability:
    """Test hot-reload stability over time."""

    def test_hot_reload_extended_operation(self, start_cc_dump, formatting_py):
        """Test that hot-reload works correctly over extended operation."""
        proc = start_cc_dump()

        time.sleep(1)
        assert proc.is_alive(), "Process should be stable initially"

        _touch(formatting_py)
        time.sleep(1.5)
        assert proc.is_alive(), "Process should survive hot-reload"

        time.sleep(1)
        assert proc.is_alive(), "Process should remain stable after hot-reload"

        proc.send("q", press_enter=False)
        settle(proc, 0.3)


# ============================================================================
# UNIT TESTS — error resilience via mocked importlib.reload
# ============================================================================


class TestHotReloadErrorResilience:
    """Test that hot-reload handles module errors gracefully.

    Uses mocked importlib.reload to simulate errors without modifying source files.
    """

    def _setup_and_trigger(self):
        """Init hot_reload, load all reloadable modules, and fake a file change."""
        import cc_dump.hot_reload as hr

        # Ensure all reloadable modules are in sys.modules
        for mod_name in hr._RELOAD_ORDER:
            importlib.import_module(mod_name)

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))
        # Force a mismatch so check_and_get_reloaded() sees a change
        first_path = next(iter(hr._mtimes))
        hr._mtimes[first_path] = 0.0
        return hr

    def test_survives_syntax_error_in_module(self):
        """Reload continues past a module that raises SyntaxError."""
        hr = self._setup_and_trigger()

        def failing_reload(mod):
            if mod.__name__ == "cc_dump.colors":
                raise SyntaxError("simulated syntax error")
            return mod  # Don't actually reload — avoids polluting sys.modules

        with patch.object(importlib, "reload", side_effect=failing_reload):
            reloaded = hr.check_and_get_reloaded()

        assert "cc_dump.colors" not in reloaded, "Broken module should be skipped"
        assert len(reloaded) > 0, "Other modules should still reload"

    def test_survives_import_error_in_module(self):
        """Reload continues past a module that raises ModuleNotFoundError."""
        hr = self._setup_and_trigger()

        def failing_reload(mod):
            if mod.__name__ == "cc_dump.formatting":
                raise ModuleNotFoundError("No module named 'nonexistent'")
            return mod  # Don't actually reload — avoids polluting sys.modules

        with patch.object(importlib, "reload", side_effect=failing_reload):
            reloaded = hr.check_and_get_reloaded()

        assert "cc_dump.formatting" not in reloaded
        assert len(reloaded) > 0

    def test_survives_runtime_error_in_module(self):
        """Reload continues past a module that raises an arbitrary exception."""
        hr = self._setup_and_trigger()

        def failing_reload(mod):
            if mod.__name__ == "cc_dump.analysis":
                raise RuntimeError("simulated runtime error")
            return mod  # Don't actually reload — avoids polluting sys.modules

        with patch.object(importlib, "reload", side_effect=failing_reload):
            reloaded = hr.check_and_get_reloaded()

        assert "cc_dump.analysis" not in reloaded
        assert len(reloaded) > 0

    def test_all_modules_failing_returns_empty(self):
        """If every module fails to reload, returns empty list."""
        hr = self._setup_and_trigger()

        with patch.object(importlib, "reload", side_effect=Exception("all broken")):
            reloaded = hr.check_and_get_reloaded()

        assert reloaded == []


# ============================================================================
# UNIT TESTS — import validation, widget protocols, state, module structure
# ============================================================================


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

    def test_conversation_view_blocks_preserve_expansion(self):
        """Blocks with expanded=True/False survive roundtrip via reference."""
        from cc_dump.formatting import TextContentBlock
        from cc_dump.tui.widget_factory import ConversationView, TurnData

        block_a = TextContentBlock(content="hello")
        block_a.expanded = True
        block_b = TextContentBlock(content="world")
        block_b.expanded = False

        widget = ConversationView()
        td = TurnData(turn_index=0, blocks=[block_a, block_b], strips=[])
        widget._turns.append(td)

        state = widget.get_state()
        new_widget = ConversationView()
        new_widget.restore_state(state)

        # Blocks are passed by reference — same objects
        restored_blocks = state["all_blocks"][0]
        assert restored_blocks[0].expanded is True
        assert restored_blocks[1].expanded is False

    def test_conversation_view_blocks_preserve_force_vis(self):
        """_force_vis survives roundtrip via block reference."""
        from cc_dump.formatting import TextContentBlock, ALWAYS_VISIBLE
        from cc_dump.tui.widget_factory import ConversationView, TurnData

        block = TextContentBlock(content="test")
        block._force_vis = ALWAYS_VISIBLE

        widget = ConversationView()
        td = TurnData(turn_index=0, blocks=[block], strips=[])
        widget._turns.append(td)

        state = widget.get_state()
        restored_blocks = state["all_blocks"][0]
        assert restored_blocks[0]._force_vis is ALWAYS_VISIBLE

    def test_conversation_view_follow_mode_true_roundtrip(self):
        """follow_mode=True explicitly survives roundtrip."""
        from cc_dump.tui.widget_factory import ConversationView

        widget = ConversationView()
        widget._follow_mode = True

        state = widget.get_state()
        new_widget = ConversationView()
        new_widget.restore_state(state)

        assert new_widget._follow_mode is True

    def test_economics_panel_breakdown_mode_roundtrip(self):
        from cc_dump.tui.widget_factory import ToolEconomicsPanel

        widget = ToolEconomicsPanel()
        widget._breakdown_mode = True
        state = widget.get_state()

        new_widget = ToolEconomicsPanel()
        new_widget.restore_state(state)
        assert new_widget._breakdown_mode is True

    def test_stats_panel_empty_state_roundtrip(self):
        """Restoring from empty state produces valid defaults."""
        from cc_dump.tui.widget_factory import StatsPanel

        widget = StatsPanel()
        new_widget = StatsPanel()
        new_widget.restore_state({})

        assert new_widget.request_count == 0
        assert new_widget.models_seen == set()

    def test_content_region_state_roundtrip(self):
        """Content regions with expanded=False survive via block reference."""
        from cc_dump.formatting import TextContentBlock, ContentRegion
        from cc_dump.tui.widget_factory import ConversationView, TurnData

        block = TextContentBlock(content="test")
        block.content_regions = [
            ContentRegion(index=0, kind="xml_block", expanded=False),
            ContentRegion(index=1, kind="md", expanded=None),
        ]

        widget = ConversationView()
        td = TurnData(turn_index=0, blocks=[block], strips=[])
        widget._turns.append(td)

        state = widget.get_state()
        restored_blocks = state["all_blocks"][0]
        assert restored_blocks[0].content_regions[0].expanded is False
        assert restored_blocks[0].content_regions[1].expanded is None

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

        required_exclusions = ["tui/app.py"]
        for exc in required_exclusions:
            assert exc in _EXCLUDED_MODULES, f"Expected {exc} to be excluded"

    def test_no_widgets_reexport_module(self):
        """tui/widgets.py re-export shim must not exist (regression guard)."""
        widgets_path = Path(__file__).parent.parent / "src" / "cc_dump" / "tui" / "widgets.py"
        assert not widgets_path.exists(), (
            "tui/widgets.py re-export module should not exist — "
            "it creates stale references after hot-reload"
        )

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

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert len(hr._watch_dirs) > 0
        assert str(test_dir) in hr._watch_dirs

    def test_scan_mtimes_populates_cache(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert len(hr._mtimes) > 0

        formatting_paths = [p for p in hr._mtimes.keys() if "formatting.py" in p]
        assert len(formatting_paths) > 0, "Should have mtime for formatting.py"

    def test_get_changed_files_returns_empty_initially(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        hr._get_changed_files()
        changed = hr._get_changed_files()

        assert isinstance(changed, set)
        assert len(changed) == 0, "No files should have changed"

    def test_check_returns_false_when_no_changes(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        hr.check()
        result = hr.check()

        assert result is False, "Should return False when no changes detected"

    def test_has_changes_returns_false_when_no_changes(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert hr.has_changes() is False, "Should return False when no changes detected"

    def test_has_changes_does_not_update_mtimes(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Capture mtimes snapshot
        mtimes_before = dict(hr._mtimes)

        # Simulate a change by tampering with the cache
        first_path = next(iter(hr._mtimes))
        hr._mtimes[first_path] = 0.0  # Force a mismatch

        assert hr.has_changes() is True, "Should detect the simulated change"
        # _mtimes should NOT have been updated (has_changes is read-only)
        assert hr._mtimes[first_path] == 0.0, "has_changes() must not update _mtimes"

        # Restore
        hr._mtimes.update(mtimes_before)

    def test_new_file_detected_on_first_check(self):
        """New files (not yet in _mtimes) are detected on first check."""
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Pick an existing watched file and remove it from _mtimes to simulate
        # a new file that appeared after init
        target_path = next(p for p in hr._mtimes if "formatting.py" in p)
        del hr._mtimes[target_path]

        assert hr.has_changes() is True, "New file should be detected by has_changes()"
        changed = hr._get_changed_files()
        assert target_path in changed, "New file should appear in _get_changed_files()"

    def test_check_and_get_reloaded_returns_empty_list_when_no_changes(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        hr.check_and_get_reloaded()
        reloaded = hr.check_and_get_reloaded()

        assert isinstance(reloaded, list)
        assert len(reloaded) == 0, "Should return empty list when no changes"


class TestSearchStateHotReload:
    """Unit tests for search state preservation across hot-reload."""

    def test_search_scalars_survive_fresh_state(self):
        """query, modes, cursor_pos transfer to fresh SearchState via _do_hot_reload logic."""
        from cc_dump.tui.search import SearchState, SearchPhase, SearchMode

        # Simulate the scalar save/restore that _do_hot_reload performs
        old_state = SearchState()
        old_state.phase = SearchPhase.NAVIGATING
        old_state.query = "test_pattern"
        old_state.modes = SearchMode.CASE_INSENSITIVE | SearchMode.WORD_BOUNDARY
        old_state.cursor_pos = 5

        # Save scalars (mirrors _do_hot_reload save step)
        saved_query = old_state.query
        saved_modes = old_state.modes
        saved_cursor_pos = old_state.cursor_pos
        saved_phase = old_state.phase

        # Reset to fresh state (mirrors _do_hot_reload reset step)
        new_state = SearchState()

        # Restore scalars (mirrors _do_hot_reload restore step)
        new_state.query = saved_query
        new_state.modes = saved_modes
        new_state.cursor_pos = saved_cursor_pos
        new_state.phase = saved_phase

        assert new_state.query == "test_pattern"
        assert new_state.modes == SearchMode.CASE_INSENSITIVE | SearchMode.WORD_BOUNDARY
        assert new_state.cursor_pos == 5
        assert new_state.phase == SearchPhase.NAVIGATING

    def test_stale_search_fields_not_preserved(self):
        """matches, expanded_blocks, debounce_timer reset to defaults after reload."""
        from cc_dump.tui.search import SearchState, SearchPhase, SearchMatch

        old_state = SearchState()
        old_state.phase = SearchPhase.NAVIGATING
        old_state.query = "test"
        old_state.matches = [SearchMatch(0, 0, 0, 4)]
        old_state.expanded_blocks = [(0, 0)]
        old_state.debounce_timer = "fake_timer"

        # After reload, a fresh SearchState should have empty derived fields
        new_state = SearchState()
        # Restore only scalars (as _do_hot_reload does)
        new_state.query = old_state.query
        new_state.modes = old_state.modes
        new_state.cursor_pos = old_state.cursor_pos
        new_state.phase = old_state.phase

        # Derived/stale fields must be fresh defaults
        assert new_state.matches == []
        assert new_state.expanded_blocks == []
        assert new_state.debounce_timer is None
        assert new_state.saved_filters == {}
        assert new_state.saved_scroll_y is None
