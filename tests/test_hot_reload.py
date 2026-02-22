"""Tests for cc-dump hot-reload functionality.

Error resilience tests run as unit tests with mocked importlib.reload.
Import validation, widget protocols, state preservation, and module structure.
"""

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ============================================================================
# UNIT TESTS — error resilience via mocked importlib.reload
# ============================================================================


class TestHotReloadErrorResilience:
    """Test that hot-reload handles module errors gracefully.

    Uses mocked importlib.reload to simulate errors without modifying source files.
    """

    def _setup_and_trigger(self):
        """Init hot_reload, load all reloadable modules, return hr module."""
        import cc_dump.hot_reload as hr

        # Ensure all reloadable modules are in sys.modules
        for mod_name in hr._RELOAD_ORDER:
            importlib.import_module(mod_name)

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))
        return hr

    def test_survives_syntax_error_in_module(self):
        """Reload continues past a module that raises SyntaxError."""
        hr = self._setup_and_trigger()

        def failing_reload(mod):
            if mod.__name__ == "cc_dump.palette":
                raise SyntaxError("simulated syntax error")
            return mod  # Don't actually reload — avoids polluting sys.modules

        with patch.object(importlib, "reload", side_effect=failing_reload):
            reloaded = hr.check_and_get_reloaded()

        assert "cc_dump.palette" not in reloaded, "Broken module should be skipped"
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
            src_dir / "tui" / "search_controller.py",
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

    def test_hot_swappable_widget_protocol_is_runtime_checkable(self):
        from cc_dump.tui.protocols import HotSwappableWidget

        class ValidWidget:
            def get_state(self):
                return {}

            def restore_state(self, state):
                return None

        assert isinstance(ValidWidget(), HotSwappableWidget)

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


class TestHotReloadSwapValidation:
    """Unit tests for hot-reload swap boundary protocol enforcement."""

    def test_validate_and_restore_widget_state_accepts_valid_widget(self):
        from cc_dump.tui.hot_reload_controller import _validate_and_restore_widget_state

        class ValidWidget:
            def __init__(self):
                self.value = 0

            def get_state(self):
                return {"value": self.value}

            def restore_state(self, state):
                self.value = state.get("value", 0)

        widget = ValidWidget()
        _validate_and_restore_widget_state(widget, {"value": 7}, widget_name="ValidWidget")
        assert widget.value == 7

    def test_validate_and_restore_widget_state_rejects_invalid_widget(self):
        from cc_dump.tui.hot_reload_controller import _validate_and_restore_widget_state

        class InvalidWidget:
            def get_state(self):
                return {}

        with pytest.raises(TypeError, match="Hot-reload widget protocol validation failed for BrokenWidget"):
            _validate_and_restore_widget_state(
                InvalidWidget(),
                {},
                widget_name="BrokenWidget",
            )


class TestHotReloadPanelRehydrate:
    """Unit tests for post-swap panel refresh from canonical stores."""

    def test_rehydrate_panels_from_store_refreshes_all_supported_panels(self):
        from cc_dump.tui.hot_reload_controller import _rehydrate_panels_from_store

        class StatsPanelStub:
            def __init__(self):
                self.calls = []

            def refresh_from_store(self, store, **kwargs):
                self.calls.append((store, kwargs))

        class StorePanelStub:
            def __init__(self):
                self.calls = []

            def refresh_from_store(self, store):
                self.calls.append(store)

        class SessionPanelStub:
            def __init__(self):
                self.calls = []

            def refresh_session_state(self, *, session_id, last_message_time):
                self.calls.append(
                    {
                        "session_id": session_id,
                        "last_message_time": last_message_time,
                    }
                )

        analytics_store = object()
        domain_store = object()

        stats = StatsPanelStub()
        economics = StorePanelStub()
        timeline = StorePanelStub()
        session = SessionPanelStub()

        app = SimpleNamespace(
            _analytics_store=analytics_store,
            _domain_store=domain_store,
            _app_state={"last_message_time": "2026-02-22T12:00:00Z"},
            _session_id="session-123",
        )
        new_panels = {
            "stats": stats,
            "economics": economics,
            "timeline": timeline,
            "session": session,
        }

        _rehydrate_panels_from_store(app, new_panels)

        assert stats.calls == [(analytics_store, {"domain_store": domain_store})]
        assert economics.calls == [analytics_store]
        assert timeline.calls == [analytics_store]
        assert session.calls == [
            {
                "session_id": "session-123",
                "last_message_time": "2026-02-22T12:00:00Z",
            }
        ]

    def test_rehydrate_panels_from_store_passes_none_store_unconditionally(self):
        from cc_dump.tui.hot_reload_controller import _rehydrate_panels_from_store

        class StorePanelStub:
            def __init__(self):
                self.calls = []

            def refresh_from_store(self, store, **kwargs):
                self.calls.append((store, kwargs))

        stats = StorePanelStub()
        app = SimpleNamespace(
            _analytics_store=None,
            _domain_store=None,
            _app_state={},
            _session_id=None,
        )

        _rehydrate_panels_from_store(app, {"stats": stats})

        assert stats.calls == [(None, {"domain_store": None})]


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
        from cc_dump.tui.widget_factory import ConversationView, FollowState

        widget = ConversationView()
        widget._follow_state = FollowState.OFF

        state = widget.get_state()

        new_widget = ConversationView()
        new_widget.restore_state(state)

        assert new_widget._follow_state == FollowState.OFF

    def test_conversation_view_blocks_preserve_expansion(self):
        """Block expanded overrides survive roundtrip via ViewOverrides serialization."""
        from cc_dump.formatting import TextContentBlock
        from cc_dump.tui.widget_factory import ConversationView, TurnData

        block_a = TextContentBlock(content="hello")
        block_b = TextContentBlock(content="world")

        widget = ConversationView()
        td = TurnData(turn_index=0, blocks=[block_a, block_b], strips=[])
        widget._turns.append(td)

        # Set expanded overrides via ViewOverrides
        widget._view_overrides.get_block(block_a.block_id).expanded = True
        widget._view_overrides.get_block(block_b.block_id).expanded = False

        state = widget.get_state()
        new_widget = ConversationView()
        new_widget.restore_state(state)

        # ViewOverrides roundtrip preserves expanded state
        assert new_widget._view_overrides.get_block(block_a.block_id).expanded is True
        assert new_widget._view_overrides.get_block(block_b.block_id).expanded is False

    def test_conversation_view_blocks_preserve_force_vis(self):
        """force_vis is transient (search state) — not serialized across hot-reload."""
        from cc_dump.formatting import TextContentBlock, ALWAYS_VISIBLE
        from cc_dump.tui.widget_factory import ConversationView, TurnData

        block = TextContentBlock(content="test")

        widget = ConversationView()
        td = TurnData(turn_index=0, blocks=[block], strips=[])
        widget._turns.append(td)

        # Set force_vis via ViewOverrides (search mode)
        widget._view_overrides.get_block(block.block_id).force_vis = ALWAYS_VISIBLE

        state = widget.get_state()
        new_widget = ConversationView()
        new_widget.restore_state(state)

        # force_vis is transient — not serialized
        assert new_widget._view_overrides.get_block(block.block_id).force_vis is None

    def test_conversation_view_follow_state_active_roundtrip(self):
        """follow_state=ACTIVE explicitly survives roundtrip."""
        from cc_dump.tui.widget_factory import ConversationView, FollowState

        widget = ConversationView()
        widget._follow_state = FollowState.ACTIVE

        state = widget.get_state()
        new_widget = ConversationView()
        new_widget.restore_state(state)

        assert new_widget._follow_state == FollowState.ACTIVE

    def test_conversation_view_follow_state_engaged_roundtrip(self):
        """follow_state=ENGAGED explicitly survives roundtrip."""
        from cc_dump.tui.widget_factory import ConversationView, FollowState

        widget = ConversationView()
        widget._follow_state = FollowState.ENGAGED

        state = widget.get_state()
        new_widget = ConversationView()
        new_widget.restore_state(state)

        assert new_widget._follow_state == FollowState.ENGAGED

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
        """Content regions survive via domain store; expanded state in ViewOverrides.

        // [LAW:one-source-of-truth] Block lists live in DomainStore.
        // ConversationView.get_state() returns only view state (follow, anchor, overrides).
        """
        from cc_dump.formatting import TextContentBlock, ContentRegion
        from cc_dump.domain_store import DomainStore
        from cc_dump.tui.widget_factory import ConversationView

        block = TextContentBlock(content="test")
        block.content_regions = [
            ContentRegion(index=0, kind="xml_block"),
            ContentRegion(index=1, kind="md"),
        ]

        widget = ConversationView()
        # Set region expanded state via ViewOverrides
        widget._view_overrides.get_region(block.block_id, 0).expanded = False
        # Add blocks directly to domain store (bypass rendering callback for unit test)
        widget._domain_store._completed.append([block])

        # Block structure lives in domain store
        completed = widget._domain_store.iter_completed_blocks()
        assert len(completed) == 1
        assert completed[0][0].content_regions[0].kind == "xml_block"
        assert completed[0][0].content_regions[1].kind == "md"

        # ViewOverrides state survives get_state/restore_state roundtrip
        state = widget.get_state()
        assert state["view_overrides"] is not None

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

        palette_idx = _RELOAD_ORDER.index("cc_dump.palette")
        analysis_idx = _RELOAD_ORDER.index("cc_dump.analysis")
        formatting_idx = _RELOAD_ORDER.index("cc_dump.formatting")
        assert formatting_idx > palette_idx, "formatting should come after palette"
        assert formatting_idx > analysis_idx, "formatting should come after analysis"

        rendering_idx = _RELOAD_ORDER.index("cc_dump.tui.rendering")
        assert rendering_idx > formatting_idx, "rendering should come after formatting"

        widget_factory_idx = _RELOAD_ORDER.index("cc_dump.tui.widget_factory")
        assert widget_factory_idx > rendering_idx, "widget_factory should come after rendering"


class TestHotReloadFileDetection:
    """Unit tests for hot-reload file classification and watch paths."""

    def test_init_sets_watch_dirs(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert len(hr._watch_dirs) > 0
        assert str(test_dir) in hr._watch_dirs

    def test_get_watch_paths_returns_copy(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        paths = hr.get_watch_paths()
        assert len(paths) > 0
        # Modifying returned list doesn't affect internal state
        paths.append("/bogus")
        assert "/bogus" not in hr.get_watch_paths()

    def test_is_reloadable_for_known_modules(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Reloadable modules
        assert hr.is_reloadable(str(test_dir / "palette.py")) is True
        assert hr.is_reloadable(str(test_dir / "formatting.py")) is True
        assert hr.is_reloadable(str(test_dir / "tui" / "rendering.py")) is True

    def test_is_reloadable_rejects_excluded(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Excluded files
        assert hr.is_reloadable(str(test_dir / "proxy.py")) is False
        assert hr.is_reloadable(str(test_dir / "cli.py")) is False
        assert hr.is_reloadable(str(test_dir / "tui" / "app.py")) is False

    def test_is_reloadable_with_relative_path(self):
        import cc_dump.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert hr.is_reloadable("palette.py") is True
        assert hr.is_reloadable("tui/rendering.py") is True
        assert hr.is_reloadable("proxy.py") is False

    def test_check_and_get_reloaded_returns_list(self):
        """check_and_get_reloaded unconditionally reloads all modules."""
        import cc_dump.hot_reload as hr

        # Ensure all reloadable modules are in sys.modules
        for mod_name in hr._RELOAD_ORDER:
            importlib.import_module(mod_name)

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # With mock to avoid real reloads
        with patch.object(importlib, "reload", side_effect=lambda m: m):
            reloaded = hr.check_and_get_reloaded()

        assert isinstance(reloaded, list)
        assert len(reloaded) > 0


class TestSearchStateHotReload:
    """Unit tests for search state preservation across hot-reload.

    // [LAW:one-source-of-truth] Identity fields live in the view store.
    // New SearchState(same_store) reads them back without manual copy.
    """

    def test_search_identity_survives_via_store(self):
        """Identity fields survive creating a new SearchState on the same store."""
        import cc_dump.view_store
        from cc_dump.tui.search import SearchState, SearchPhase, SearchMode

        store = cc_dump.view_store.create()
        old_state = SearchState(store)
        old_state.phase = SearchPhase.NAVIGATING
        old_state.query = "test_pattern"
        old_state.modes = SearchMode.CASE_INSENSITIVE | SearchMode.WORD_BOUNDARY
        old_state.cursor_pos = 5

        # Simulate hot-reload: new SearchState on the same store
        new_state = SearchState(store)

        assert new_state.query == "test_pattern"
        assert new_state.modes == SearchMode.CASE_INSENSITIVE | SearchMode.WORD_BOUNDARY
        assert new_state.cursor_pos == 5
        assert new_state.phase == SearchPhase.NAVIGATING

    def test_transient_fields_reset_on_new_state(self):
        """matches, expanded_blocks, debounce_timer reset to defaults on new SearchState."""
        import cc_dump.view_store
        from cc_dump.tui.search import SearchState, SearchPhase, SearchMatch

        store = cc_dump.view_store.create()
        old_state = SearchState(store)
        old_state.phase = SearchPhase.NAVIGATING
        old_state.query = "test"
        old_state.matches = [SearchMatch(0, 0, 0, 4)]
        old_state.expanded_blocks = [(0, 0)]
        old_state.debounce_timer = "fake_timer"

        # New SearchState on same store — transient fields are fresh
        new_state = SearchState(store)

        # Identity survived
        assert new_state.query == "test"
        assert new_state.phase == SearchPhase.NAVIGATING

        # Transient fields are fresh defaults
        assert new_state.matches == []
        assert new_state.expanded_blocks == []
        assert new_state.debounce_timer is None
        assert new_state.saved_filters == {}
        assert new_state.saved_scroll_y is None
