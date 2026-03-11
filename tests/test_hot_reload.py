"""Tests for cc-dump hot-reload functionality.

Error resilience tests run as unit tests with mocked importlib.reload.
Import validation, widget protocols, state preservation, and module structure.
"""

import ast
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

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
        import cc_dump.app.hot_reload as hr

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
            if mod.__name__ == "cc_dump.core.palette":
                raise SyntaxError("simulated syntax error")
            return mod  # Don't actually reload — avoids polluting sys.modules

        with patch.object(importlib, "reload", side_effect=failing_reload):
            reloaded = hr.check_and_get_reloaded()

        assert "cc_dump.core.palette" not in reloaded, "Broken module should be skipped"
        assert len(reloaded) > 0, "Other modules should still reload"

    def test_survives_import_error_in_module(self):
        """Reload continues past a module that raises ModuleNotFoundError."""
        hr = self._setup_and_trigger()

        def failing_reload(mod):
            if mod.__name__ == "cc_dump.core.formatting":
                raise ModuleNotFoundError("No module named 'nonexistent'")
            return mod  # Don't actually reload — avoids polluting sys.modules

        with patch.object(importlib, "reload", side_effect=failing_reload):
            reloaded = hr.check_and_get_reloaded()

        assert "cc_dump.core.formatting" not in reloaded
        assert len(reloaded) > 0

    def test_survives_runtime_error_in_module(self):
        """Reload continues past a module that raises an arbitrary exception."""
        hr = self._setup_and_trigger()

        def failing_reload(mod):
            if mod.__name__ == "cc_dump.core.analysis":
                raise RuntimeError("simulated runtime error")
            return mod  # Don't actually reload — avoids polluting sys.modules

        with patch.object(importlib, "reload", side_effect=failing_reload):
            reloaded = hr.check_and_get_reloaded()

        assert "cc_dump.core.analysis" not in reloaded
        assert len(reloaded) > 0

    def test_all_modules_failing_returns_empty(self):
        """If every module fails to reload, returns empty list."""
        hr = self._setup_and_trigger()

        with patch.object(importlib, "reload", side_effect=Exception("all broken")):
            reloaded = hr.check_and_get_reloaded()

        assert reloaded == []


class TestHotReloadWatcherLifecycle:
    """Unit tests for file watcher stream lifecycle cleanup."""

    def test_stop_file_watcher_disposes_stream(self):
        import cc_dump.tui.hot_reload_controller as controller

        class StreamStub:
            def __init__(self):
                self.disposed = False

            def dispose(self):
                self.disposed = True

        stream = StreamStub()
        controller._watcher_stream = stream

        controller.stop_file_watcher()

        assert stream.disposed is True
        assert controller._watcher_stream is None

    def test_stop_file_watcher_noop_without_stream(self):
        import cc_dump.tui.hot_reload_controller as controller

        controller._watcher_stream = None
        controller.stop_file_watcher()
        assert controller._watcher_stream is None


class TestHotReloadMountSeam:
    @pytest.mark.asyncio
    async def test_mount_replacement_conversation_uses_original_non_app_parent(self):
        from cc_dump.tui.hot_reload_controller import _mount_replacement_conversation

        parent = AsyncMock()
        app = AsyncMock()
        new_conv = object()
        prev_widget = object()

        await _mount_replacement_conversation(
            app,
            new_conv,
            prev_widget=prev_widget,
            old_conv_parent=parent,
        )

        parent.mount.assert_awaited_once_with(new_conv)
        app.mount.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mount_replacement_conversation_uses_app_mount_for_root_parent(self):
        from cc_dump.tui.hot_reload_controller import _mount_replacement_conversation

        app = AsyncMock()
        new_conv = object()
        prev_widget = object()

        await _mount_replacement_conversation(
            app,
            new_conv,
            prev_widget=prev_widget,
            old_conv_parent=app,
        )

        app.mount.assert_awaited_once_with(new_conv, after=prev_widget)


class TestHotReloadPanelIdentity:
    def test_assign_replacement_identity_reconciles_panel_ids(self, monkeypatch):
        import cc_dump.tui.hot_reload_controller as controller
        import cc_dump.tui.panel_registry as panel_registry

        monkeypatch.setattr(
            panel_registry,
            "PANEL_REGISTRY",
            [
                panel_registry.PanelSpec("stats", "stats-panel", "cc_dump.tui.widget_factory.create_stats_panel"),
                panel_registry.PanelSpec("session", "session-panel", "cc_dump.tui.session_panel.create_session_panel"),
            ],
        )

        app = SimpleNamespace(
            _logs_id="logs-panel",
            _info_id="info-panel",
            _panel_ids={"stats": "old-stats-panel", "removed": "removed-panel"},
        )
        snapshot = controller._WidgetSwapSnapshot(
            conversations=[],
            old_logs=None,
            old_info=None,
            old_footer=None,
            logs_state={},
            info_state={},
            old_panels={},
            panel_states={},
            active_panel="stats",
            logs_visible=True,
            info_visible=False,
        )
        new_logs = SimpleNamespace(id=None, display=None)
        new_info = SimpleNamespace(id=None, display=None)
        new_panels = {
            "stats": SimpleNamespace(id=None, display=None),
            "session": SimpleNamespace(id=None, display=None),
        }

        controller._assign_replacement_identity(
            app,
            snapshot=snapshot,
            new_conversations={},
            new_panels=new_panels,
            new_logs=new_logs,
            new_info=new_info,
        )

        assert app._panel_ids == {
            "stats": "stats-panel",
            "session": "session-panel",
        }
        assert new_panels["stats"].id == "stats-panel"
        assert new_panels["stats"].display is True
        assert new_panels["session"].id == "session-panel"
        assert new_panels["session"].display is False
        assert new_logs.id == "logs-panel"
        assert new_logs.display is True
        assert new_info.id == "info-panel"
        assert new_info.display is False

    @pytest.mark.asyncio
    async def test_remove_old_widgets_drops_stale_panels(self):
        import cc_dump.tui.hot_reload_controller as controller

        stale_panel = AsyncMock()
        current_panel = AsyncMock()
        snapshot = controller._WidgetSwapSnapshot(
            conversations=[],
            old_logs=None,
            old_info=None,
            old_footer=None,
            logs_state={},
            info_state={},
            old_panels={"removed": stale_panel, "stats": current_panel},
            panel_states={},
            active_panel="stats",
            logs_visible=True,
            info_visible=True,
        )

        await controller._remove_old_widgets(snapshot)

        stale_panel.remove.assert_awaited_once()
        current_panel.remove.assert_awaited_once()


@pytest.mark.textual
class TestHotReloadMultiSessionTabs:
    async def test_replace_all_widgets_preserves_all_session_tabs(self):
        from tests.harness import run_app
        from cc_dump.tui import hot_reload_controller as hr

        account_id = "11111111-2222-3333-4444-555555555555"
        session_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        session_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        def _entry(session_id: str, user_text: str, assistant_text: str):
            user_id = f"user_deadbeef_account_{account_id}_session_{session_id}"
            req_body = {
                "model": "claude-sonnet-4-5-20250929",
                "max_tokens": 1024,
                "metadata": {"user_id": user_id},
                "messages": [{"role": "user", "content": user_text}],
            }
            complete = {
                "id": f"msg-{session_id[:8]}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-5-20250929",
                "content": [{"type": "text", "text": assistant_text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            return (
                {"content-type": "application/json"},
                req_body,
                200,
                {"content-type": "application/json"},
                complete,
                "anthropic",
            )

        replay_data = [
            _entry(session_a, "session-a-request", "session-a-response"),
            _entry(session_b, "session-b-request", "session-b-response"),
        ]

        async with run_app(replay_data=replay_data) as (pilot, app):
            tabs = app._get_conv_tabs()
            assert tabs is not None

            # With one-tab-per-instance, both sessions share the default tab.
            default_key = app._default_session_key
            default_tab = app._session_tab_ids[default_key]
            tabs.active = default_tab
            await pilot.pause()

            old_conv_id = id(app._get_conv(session_key=default_key))

            await hr.replace_all_widgets(app)
            await pilot.pause()

            new_conv = app._get_conv(session_key=default_key)
            assert new_conv is not None
            assert id(new_conv) != old_conv_id

            # Both sessions' turns should be in the default tab's ConversationView.
            assert len(new_conv._turns) >= 4  # At least 2 turns per replay entry
            assert tabs.active == default_tab
            assert app._domain_store is app._get_domain_store(default_key)


# ============================================================================
# UNIT TESTS — import validation, widget protocols, state, module structure
# ============================================================================


class TestImportValidation:
    """Test import behavior + alias refresh semantics for hot-reload."""

    def test_reload_order_includes_shared_pure_modules(self):
        import cc_dump.app.hot_reload as hr

        assert "cc_dump.core.coerce" in hr._RELOAD_ORDER
        assert "cc_dump.app.error_models" in hr._RELOAD_ORDER

    def test_hot_reload_refreshes_top_level_from_import_aliases(self):
        import cc_dump.app.hot_reload as hr

        provider_name = "cc_dump._hr_test_provider"
        consumer_name = "cc_dump._hr_test_consumer"

        provider = ModuleType(provider_name)

        def _old_func() -> str:
            return "old"

        _old_func.__module__ = provider_name
        provider.some_func = _old_func
        consumer = ModuleType(consumer_name)
        # Simulate: from cc_dump._hr_test_provider import some_func
        consumer.some_func = provider.some_func

        with patch.dict(
            "sys.modules",
            {
                provider_name: provider,
                consumer_name: consumer,
            },
            clear=False,
        ):
            with patch.object(hr, "_RELOAD_ORDER", [provider_name]):
                with patch.object(importlib, "reload") as mock_reload:
                    def _reload_module(mod):
                        def _new_func() -> str:
                            return "new"
                        _new_func.__module__ = provider_name
                        mod.some_func = _new_func
                        return mod

                    mock_reload.side_effect = _reload_module
                    reloaded = hr.check_and_get_reloaded()

        assert reloaded == [provider_name]
        assert consumer.some_func is provider.some_func
        assert consumer.some_func() == "new"

    def test_hot_reload_does_not_rebind_shared_primitive_aliases(self):
        import cc_dump.app.hot_reload as hr

        provider_name = "cc_dump._hr_test_provider_primitives"
        consumer_name = "cc_dump._hr_test_consumer_primitives"
        unrelated_name = "cc_dump._hr_test_unrelated_primitives"
        original_token = sys.intern("cc_dump_hr_test_token")
        replacement_token = sys.intern("cc_dump_hr_test_token_reloaded")

        provider = ModuleType(provider_name)
        provider.count = original_token

        consumer = ModuleType(consumer_name)
        consumer.count = provider.count

        unrelated = ModuleType(unrelated_name)
        unrelated.also_count = original_token

        with patch.dict(
            "sys.modules",
            {
                provider_name: provider,
                consumer_name: consumer,
                unrelated_name: unrelated,
            },
            clear=False,
        ):
            with patch.object(hr, "_RELOAD_ORDER", [provider_name]):
                with patch.object(importlib, "reload") as mock_reload:
                    mock_reload.side_effect = (
                        lambda mod: setattr(mod, "count", replacement_token) or mod
                    )
                    reloaded = hr.check_and_get_reloaded()

        assert reloaded == [provider_name]
        # Primitive exports are intentionally excluded from alias refresh.
        assert consumer.count is original_token
        assert unrelated.also_count is original_token
        assert provider.count is replacement_token

    def test_hot_reload_applies_alias_replacements_when_new_value_is_none(self):
        import cc_dump.app.hot_reload as hr

        provider_name = "cc_dump._hr_test_provider_none"
        consumer_name = "cc_dump._hr_test_consumer_none"

        provider = ModuleType(provider_name)

        def _old_func() -> str:
            return "old"

        _old_func.__module__ = provider_name
        provider.some_func = _old_func

        consumer = ModuleType(consumer_name)
        consumer.some_func = provider.some_func

        with patch.dict(
            "sys.modules",
            {
                provider_name: provider,
                consumer_name: consumer,
            },
            clear=False,
        ):
            with patch.object(hr, "_RELOAD_ORDER", [provider_name]):
                with patch.object(importlib, "reload") as mock_reload:
                    mock_reload.side_effect = lambda mod: setattr(mod, "some_func", None) or mod
                    reloaded = hr.check_and_get_reloaded()

        assert reloaded == [provider_name]
        assert provider.some_func is None
        assert consumer.some_func is None

    def test_reloadable_modules_prefer_top_level_from_imports(self):
        src_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        policy_modules = [
            src_dir / "app" / "view_store.py",
            src_dir / "app" / "settings_store.py",
            src_dir / "tui" / "error_indicator.py",
        ]
        violations: list[str] = []

        for module_path in policy_modules:
            tree = ast.parse(module_path.read_text(), filename=str(module_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("cc_dump."):
                            violations.append(
                                f"{module_path.name}:{node.lineno}: import {alias.name}"
                            )

        assert not violations, (
            "Reloadable modules should prefer top-level `from ... import ...` for cc_dump imports. "
            f"Violations: {violations}"
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
        )
        from cc_dump.tui.session_panel import SessionPanel
        from cc_dump.tui.protocols import validate_widget_protocol

        widgets = [
            ConversationView(),
            StatsPanel(),
            SessionPanel(),
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


class TestWidgetStatePreservation:
    """Unit tests for widget state get/restore cycle."""

    def test_stats_panel_state_roundtrip(self):
        from cc_dump.tui.widget_factory import StatsPanel

        widget = StatsPanel()
        widget._view_index = 2

        state = widget.get_state()

        new_widget = StatsPanel()
        new_widget.restore_state(state)

        assert new_widget._view_index == 2

    def test_conversation_view_state_roundtrip(self):
        from cc_dump.tui.widget_factory import ConversationView, FollowState

        widget = ConversationView()
        widget._follow_state = FollowState.OFF

        state = widget.get_state()

        new_widget = ConversationView()
        new_widget.restore_state(state)

        assert new_widget._follow_state == FollowState.OFF

    def test_conversation_view_blocks_preserve_expandable_metadata(self):
        """Block expandability metadata survives roundtrip via ViewOverrides serialization."""
        from cc_dump.core.formatting import TextContentBlock
        from cc_dump.tui.widget_factory import ConversationView, TurnData

        block_a = TextContentBlock(content="hello")
        block_b = TextContentBlock(content="world")

        widget = ConversationView()
        td = TurnData(turn_index=0, blocks=[block_a, block_b], strips=[])
        widget._turns.append(td)

        # Set expandability metadata via ViewOverrides
        widget._view_overrides.get_block(block_a.block_id).expandable = True
        widget._view_overrides.get_block(block_b.block_id).expandable = False

        state = widget.get_state()
        new_widget = ConversationView()
        new_widget.restore_state(state)

        # ViewOverrides roundtrip preserves block metadata
        assert new_widget._view_overrides.get_block(block_a.block_id).expandable is True
        assert new_widget._view_overrides.get_block(block_b.block_id).expandable is False

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

    def test_conversation_view_restore_state_coerces_invalid_scroll_anchor(self):
        """Malformed persisted anchor values are coerced to safe defaults."""
        from cc_dump.tui.widget_factory import ConversationView

        widget = ConversationView()
        widget.restore_state(
            {
                "scroll_anchor": {
                    "turn_index": "not-an-int",
                    "line_in_turn": "-9",
                }
            }
        )
        widget._rebuild_from_state({})

        assert widget._scroll_anchor is not None
        assert widget._scroll_anchor.turn_index == 0
        assert widget._scroll_anchor.line_in_turn == 0

    def test_stats_panel_empty_state_roundtrip(self):
        """Restoring from empty state produces valid defaults."""
        from cc_dump.tui.widget_factory import StatsPanel

        new_widget = StatsPanel()
        new_widget.restore_state({})

        assert new_widget._view_index == 0

    def test_content_region_state_roundtrip(self):
        """Content regions survive via domain store; expanded state in ViewOverrides.

        // [LAW:one-source-of-truth] Block lists live in DomainStore.
        // ConversationView.get_state() returns only view state (follow, anchor, overrides).
        """
        from cc_dump.core.formatting import TextContentBlock, ContentRegion
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

class TestHotReloadModuleStructure:
    """Unit tests for hot-reload module configuration."""

    def test_reload_order_is_defined(self):
        from cc_dump.app.hot_reload import _RELOAD_ORDER

        assert isinstance(_RELOAD_ORDER, list)
        assert len(_RELOAD_ORDER) > 0

        expected_modules = [
            "cc_dump.core.formatting",
            "cc_dump.pipeline.router",
            "cc_dump.tui.rendering",
            "cc_dump.tui.widget_factory",
        ]
        for mod in expected_modules:
            assert mod in _RELOAD_ORDER, f"Expected module {mod} in reload order"

    def test_excluded_files_contain_stable_boundaries(self):
        from cc_dump.app.hot_reload import _EXCLUDED_FILES

        assert isinstance(_EXCLUDED_FILES, set)

        required_exclusions = ["pipeline/proxy.py", "cli.py", "hot_reload.py"]
        for exc in required_exclusions:
            assert exc in _EXCLUDED_FILES, f"Expected {exc} to be excluded"

    def test_excluded_modules_contain_live_instances(self):
        from cc_dump.app.hot_reload import _EXCLUDED_MODULES

        assert isinstance(_EXCLUDED_MODULES, set)

        required_exclusions = ["tui/app.py", "tui/hot_reload_controller.py"]
        for exc in required_exclusions:
            assert exc in _EXCLUDED_MODULES, f"Expected {exc} to be excluded"

        # [LAW:locality-or-seam] Pure/controller modules should remain reloadable.
        assert "tui/search_controller.py" not in _EXCLUDED_MODULES
        assert "tui/category_config.py" not in _EXCLUDED_MODULES
        assert "tui/panel_registry.py" not in _EXCLUDED_MODULES

    def test_no_widgets_reexport_module(self):
        """tui/widgets.py re-export shim must not exist (regression guard)."""
        widgets_path = Path(__file__).parent.parent / "src" / "cc_dump" / "tui" / "widgets.py"
        assert not widgets_path.exists(), (
            "tui/widgets.py re-export module should not exist — "
            "it creates stale references after hot-reload"
        )

    def test_reload_order_respects_dependencies(self):
        from cc_dump.app.hot_reload import _RELOAD_ORDER

        palette_idx = _RELOAD_ORDER.index("cc_dump.core.palette")
        analysis_idx = _RELOAD_ORDER.index("cc_dump.core.analysis")
        formatting_idx = _RELOAD_ORDER.index("cc_dump.core.formatting")
        assert formatting_idx > palette_idx, "formatting should come after palette"
        assert formatting_idx > analysis_idx, "formatting should come after analysis"

        rendering_idx = _RELOAD_ORDER.index("cc_dump.tui.rendering")
        assert rendering_idx > formatting_idx, "rendering should come after formatting"

        widget_factory_idx = _RELOAD_ORDER.index("cc_dump.tui.widget_factory")
        assert widget_factory_idx > rendering_idx, "widget_factory should come after rendering"


class TestHotReloadFileDetection:
    """Unit tests for hot-reload file classification and watch paths."""

    def test_init_sets_watch_dirs(self):
        import cc_dump.app.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert len(hr._watch_dirs) > 0
        assert str(test_dir) in hr._watch_dirs

    def test_get_watch_paths_returns_copy(self):
        import cc_dump.app.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        paths = hr.get_watch_paths()
        assert len(paths) > 0
        # Modifying returned list doesn't affect internal state
        paths.append("/bogus")
        assert "/bogus" not in hr.get_watch_paths()

    def test_is_reloadable_for_known_modules(self):
        import cc_dump.app.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Reloadable modules
        assert hr.is_reloadable(str(test_dir / "core" / "palette.py")) is True
        assert hr.is_reloadable(str(test_dir / "core" / "formatting.py")) is True
        assert hr.is_reloadable(str(test_dir / "tui" / "rendering.py")) is True
        assert hr.is_reloadable(str(test_dir / "tui" / "search_controller.py")) is True
        assert hr.is_reloadable(str(test_dir / "tui" / "category_config.py")) is True
        assert hr.is_reloadable(str(test_dir / "tui" / "panel_registry.py")) is True

    def test_is_reloadable_rejects_excluded(self):
        import cc_dump.app.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        # Excluded files
        assert hr.is_reloadable(str(test_dir / "pipeline" / "proxy.py")) is False
        assert hr.is_reloadable(str(test_dir / "cli.py")) is False
        assert hr.is_reloadable(str(test_dir / "tui" / "app.py")) is False

    def test_is_reloadable_with_relative_path(self):
        import cc_dump.app.hot_reload as hr

        test_dir = Path(__file__).parent.parent / "src" / "cc_dump"
        hr.init(str(test_dir))

        assert hr.is_reloadable("core/palette.py") is True
        assert hr.is_reloadable("tui/rendering.py") is True
        assert hr.is_reloadable("pipeline/proxy.py") is False

    def test_check_and_get_reloaded_returns_list(self):
        """check_and_get_reloaded unconditionally reloads all modules."""
        import cc_dump.app.hot_reload as hr

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
        import cc_dump.app.view_store
        from cc_dump.tui.search import SearchState, SearchPhase, SearchMode

        store = cc_dump.app.view_store.create()
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
        """Transient fields reset to defaults on new SearchState."""
        import cc_dump.app.view_store
        from cc_dump.tui.search import SearchState, SearchPhase, SearchMatch

        store = cc_dump.app.view_store.create()
        old_state = SearchState(store)
        old_state.phase = SearchPhase.NAVIGATING
        old_state.query = "test"
        old_state.matches = [SearchMatch(0, 0, 0, 4)]
        old_state.debounce_timer = "fake_timer"

        # New SearchState on same store — transient fields are fresh
        new_state = SearchState(store)

        # Identity survived
        assert new_state.query == "test"
        assert new_state.phase == SearchPhase.NAVIGATING

        # Transient fields are fresh defaults
        assert new_state.matches == []
        assert new_state.debounce_timer is None
        assert new_state.saved_filters == {}
        assert new_state.saved_scroll_y is None
