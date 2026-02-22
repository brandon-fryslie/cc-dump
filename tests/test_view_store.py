"""Tests for view_store — reactive category visibility + panel/follow state."""

from unittest.mock import MagicMock

import pytest
from textual.css.query import NoMatches

import cc_dump.view_store
from cc_dump.formatting import VisState
from cc_dump.tui.category_config import CATEGORY_CONFIG
from snarfx import autorun, transaction
from snarfx import textual as stx


class TestSchema:
    def test_schema_has_41_keys(self):
        # 6 categories × 3 axes + 5 panel/follow + 9 footer + 5 side-channel + 4 search
        assert len(cc_dump.view_store.SCHEMA) == 41

    def test_schema_keys_from_category_config(self):
        for _, name, _, _ in CATEGORY_CONFIG:
            assert f"vis:{name}" in cc_dump.view_store.SCHEMA
            assert f"full:{name}" in cc_dump.view_store.SCHEMA
            assert f"exp:{name}" in cc_dump.view_store.SCHEMA

    def test_schema_defaults_match_category_config(self):
        for _, name, _, default in CATEGORY_CONFIG:
            assert cc_dump.view_store.SCHEMA[f"vis:{name}"] == default.visible
            assert cc_dump.view_store.SCHEMA[f"full:{name}"] == default.full
            assert cc_dump.view_store.SCHEMA[f"exp:{name}"] == default.expanded


class TestCreate:
    def test_creates_store_with_defaults(self):
        store = cc_dump.view_store.create()
        # user defaults: visible=True, full=True, expanded=True
        assert store.get("vis:user") is True
        assert store.get("full:user") is True
        assert store.get("exp:user") is True
        # metadata defaults: visible=False, full=False, expanded=False
        assert store.get("vis:metadata") is False
        assert store.get("full:metadata") is False
        assert store.get("exp:metadata") is False

    def test_active_filters_computed_attached(self):
        store = cc_dump.view_store.create()
        filters = store.active_filters.get()
        assert isinstance(filters, dict)
        assert len(filters) == 6  # 6 categories


class TestActiveFiltersComputed:
    def test_returns_correct_vis_states(self):
        store = cc_dump.view_store.create()
        filters = store.active_filters.get()
        assert filters["user"] == VisState(True, True, True)
        assert filters["metadata"] == VisState(False, False, False)
        assert filters["tools"] == VisState(True, False, False)

    def test_updates_on_set(self):
        store = cc_dump.view_store.create()
        store.set("vis:metadata", True)
        filters = store.active_filters.get()
        assert filters["metadata"].visible is True

    def test_updates_on_multi_set(self):
        store = cc_dump.view_store.create()
        store.update({"vis:metadata": True, "full:metadata": True, "exp:metadata": True})
        filters = store.active_filters.get()
        assert filters["metadata"] == VisState(True, True, True)


class TestTransactionBatching:
    def test_transaction_fires_autorun_once(self):
        store = cc_dump.view_store.create()
        log = []
        autorun(lambda: log.append(store.active_filters.get()["tools"]))
        # Initial fire
        assert len(log) == 1

        with transaction():
            store.set("vis:tools", False)
            store.set("full:tools", True)
            store.set("exp:tools", True)

        # Single additional fire, not three
        assert len(log) == 2
        assert log[1] == VisState(False, True, True)

    def test_update_batches(self):
        store = cc_dump.view_store.create()
        log = []
        autorun(lambda: log.append(store.active_filters.get()["system"]))
        assert len(log) == 1

        store.update({"vis:system": False, "full:system": True})
        assert len(log) == 2
        assert log[1] == VisState(False, True, False)


class TestReconcile:
    def test_reconcile_preserves_values(self):
        store = cc_dump.view_store.create()
        store.set("vis:metadata", True)
        store.set("full:tools", True)

        store.reconcile(cc_dump.view_store.SCHEMA, lambda s: [])

        assert store.get("vis:metadata") is True
        assert store.get("full:tools") is True

    def test_reconcile_re_registers_reactions(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app._rerender_if_mounted = MagicMock()
        context = {"app": app}

        disposers = cc_dump.view_store.setup_reactions(store, context)
        store._reaction_disposers = disposers

        # Initial autorun fires rerender
        initial_calls = app._rerender_if_mounted.call_count

        # Reconcile re-registers reactions
        store.reconcile(
            cc_dump.view_store.SCHEMA,
            lambda s: cc_dump.view_store.setup_reactions(s, context),
        )

        store.set("vis:user", False)
        assert app._rerender_if_mounted.call_count > initial_calls


class TestGetCategoryState:
    def test_returns_correct_vis_state(self):
        store = cc_dump.view_store.create()
        state = cc_dump.view_store.get_category_state(store, "user")
        assert state == VisState(True, True, True)

    def test_reflects_mutations(self):
        store = cc_dump.view_store.create()
        store.set("vis:user", False)
        state = cc_dump.view_store.get_category_state(store, "user")
        assert state == VisState(False, True, True)


class TestSetupReactions:
    def test_autorun_calls_rerender(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app._rerender_if_mounted = MagicMock()
        context = {"app": app}

        disposers = cc_dump.view_store.setup_reactions(store, context)
        store._reaction_disposers = disposers

        # autorun fires immediately on setup
        initial_calls = app._rerender_if_mounted.call_count
        assert initial_calls >= 1

        store.set("vis:tools", False)
        assert app._rerender_if_mounted.call_count > initial_calls

    def test_no_context_returns_empty(self):
        store = cc_dump.view_store.create()
        disposers = cc_dump.view_store.setup_reactions(store)
        assert disposers == []

    def test_no_app_in_context_returns_empty(self):
        store = cc_dump.view_store.create()
        disposers = cc_dump.view_store.setup_reactions(store, {})
        assert disposers == []


class TestPanelAndFollowSchema:
    def test_panel_active_default(self):
        assert cc_dump.view_store.SCHEMA["panel:active"] == "session"

    def test_panel_booleans_default_false(self):
        assert cc_dump.view_store.SCHEMA["panel:side_channel"] is False
        assert cc_dump.view_store.SCHEMA["panel:settings"] is False
        assert cc_dump.view_store.SCHEMA["panel:launch_config"] is False

    def test_follow_default(self):
        assert cc_dump.view_store.SCHEMA["nav:follow"] == "active"

    def test_store_has_panel_keys(self):
        store = cc_dump.view_store.create()
        assert store.get("panel:active") == "session"
        assert store.get("panel:side_channel") is False
        assert store.get("panel:settings") is False
        assert store.get("panel:launch_config") is False
        assert store.get("nav:follow") == "active"

    def test_panel_active_set_and_get(self):
        store = cc_dump.view_store.create()
        store.set("panel:active", "stats")
        assert store.get("panel:active") == "stats"

    def test_follow_set_and_get(self):
        store = cc_dump.view_store.create()
        store.set("nav:follow", "off")
        assert store.get("nav:follow") == "off"


class TestPanelActiveReaction:
    def test_reaction_fires_on_panel_change(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app.is_running = True
        app._rerender_if_mounted = MagicMock()
        app._sync_panel_display = MagicMock()
        push_panel = MagicMock()
        context = {"app": app, "push_panel_change": push_panel}

        disposers = cc_dump.view_store.setup_reactions(store, context)

        push_panel.reset_mock()

        store.set("panel:active", "stats")

        push_panel.assert_called_with("stats")

    def test_reaction_guarded_during_stx_pause(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app.is_running = True
        app._rerender_if_mounted = MagicMock()
        push_panel = MagicMock()
        context = {"app": app, "push_panel_change": push_panel}

        disposers = cc_dump.view_store.setup_reactions(store, context)
        push_panel.reset_mock()

        with stx.pause(app):
            store.set("panel:active", "timeline")

        push_panel.assert_not_called()

    def test_reaction_guarded_before_running(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app.is_running = False
        app._rerender_if_mounted = MagicMock()
        push_panel = MagicMock()
        context = {"app": app, "push_panel_change": push_panel}

        disposers = cc_dump.view_store.setup_reactions(store, context)
        push_panel.reset_mock()

        store.set("panel:active", "economics")

        push_panel.assert_not_called()


class TestReconcileWithNewKeys:
    def test_reconcile_preserves_panel_values(self):
        store = cc_dump.view_store.create()
        store.set("panel:active", "timeline")
        store.set("nav:follow", "off")

        store.reconcile(cc_dump.view_store.SCHEMA, lambda s: [])

        assert store.get("panel:active") == "timeline"
        assert store.get("nav:follow") == "off"

    def test_reconcile_adds_new_keys_with_defaults(self):
        """Reconcile adds all keys with defaults."""
        store = cc_dump.view_store.create()
        # Simulate reconcile (which normally happens after hot-reload)
        store.reconcile(cc_dump.view_store.SCHEMA, lambda s: [])

        # All keys present with defaults
        assert store.get("panel:active") == "session"
        assert store.get("panel:side_channel") is False
        assert store.get("nav:follow") == "active"
        assert store.get("filter:active") is None
        assert store.get("tmux:available") is False
        assert store.get("streams:active") == ()
        assert store.get("streams:focused") == ""
        assert store.get("streams:view") == "focused"
        assert store.get("sc:loading") is False
        assert store.get("sc:purpose_usage") == {}


class TestFooterStateComputed:
    def test_returns_dict_with_category_keys(self):
        store = cc_dump.view_store.create()
        state = store.footer_state.get()
        assert isinstance(state, dict)
        # Should contain all 6 category VisStates
        for _, name, _, _ in CATEGORY_CONFIG:
            assert name in state
            assert isinstance(state[name], VisState)

    def test_contains_panel_and_follow(self):
        store = cc_dump.view_store.create()
        state = store.footer_state.get()
        assert state["active_panel"] == "session"
        assert state["follow_state"] == "active"

    def test_contains_footer_inputs(self):
        store = cc_dump.view_store.create()
        state = store.footer_state.get()
        assert state["active_filterset"] is None
        assert state["tmux_available"] is False
        assert state["tmux_auto_zoom"] is False
        assert state["tmux_zoomed"] is False
        assert state["active_launch_config_name"] == ""
        assert state["active_streams"] == ()
        assert state["focused_stream_id"] == ""
        assert state["stream_view_mode"] == "focused"

    def test_updates_on_store_change(self):
        store = cc_dump.view_store.create()
        store.set("filter:active", "1")
        state = store.footer_state.get()
        assert state["active_filterset"] == "1"

    def test_stream_chip_state_updates(self):
        store = cc_dump.view_store.create()
        store.set("streams:active", (("req-1", "main", "main"),))
        store.set("streams:focused", "req-1")
        state = store.footer_state.get()
        assert state["active_streams"] == (("req-1", "main", "main"),)
        assert state["focused_stream_id"] == "req-1"

    def test_stream_view_mode_updates(self):
        store = cc_dump.view_store.create()
        store.set("streams:view", "lanes")
        state = store.footer_state.get()
        assert state["stream_view_mode"] == "lanes"


class TestErrorItemsComputed:
    def test_empty_when_no_errors(self):
        store = cc_dump.view_store.create()
        items = store.error_items.get()
        assert items == []

    def test_stale_files_converted_to_error_items(self):
        import cc_dump.tui.error_indicator
        store = cc_dump.view_store.create()
        store.stale_files.append("src/cc_dump/foo.py")
        items = store.error_items.get()
        assert len(items) == 1
        assert items[0].id == "stale"
        assert items[0].summary == "foo.py"

    def test_exception_items_included(self):
        import cc_dump.tui.error_indicator
        ErrorItem = cc_dump.tui.error_indicator.ErrorItem
        store = cc_dump.view_store.create()
        exc_item = ErrorItem("exc-1", "\U0001f4a5", "ValueError: bad")
        store.exception_items.append(exc_item)
        items = store.error_items.get()
        assert len(items) == 1
        assert items[0].summary == "ValueError: bad"

    def test_combines_stale_and_exceptions(self):
        import cc_dump.tui.error_indicator
        ErrorItem = cc_dump.tui.error_indicator.ErrorItem
        store = cc_dump.view_store.create()
        store.stale_files.append("src/cc_dump/bar.py")
        store.exception_items.append(ErrorItem("exc-1", "\U0001f4a5", "TypeError: oops"))
        items = store.error_items.get()
        assert len(items) == 2
        assert items[0].summary == "bar.py"
        assert items[1].summary == "TypeError: oops"


class TestScPanelStateComputed:
    def test_defaults(self):
        store = cc_dump.view_store.create()
        state = store.sc_panel_state.get()
        assert isinstance(state, dict)
        assert state["enabled"] is False  # no settings_store wired
        assert state["loading"] is False
        assert state["result_text"] == ""
        assert state["result_source"] == ""
        assert state["result_elapsed_ms"] == 0
        assert state["purpose_usage"] == {}

    def test_updates_from_store(self):
        store = cc_dump.view_store.create()
        store.set("sc:loading", True)
        store.set("sc:result_text", "summary")
        store.set("sc:purpose_usage", {"block_summary": {"turns": 1}})
        state = store.sc_panel_state.get()
        assert state["loading"] is True
        assert state["result_text"] == "summary"
        assert state["purpose_usage"] == {"block_summary": {"turns": 1}}


class TestFooterReaction:
    def test_footer_reaction_fires_on_key_change(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app.is_running = True
        app._rerender_if_mounted = MagicMock()
        push_footer = MagicMock()
        context = {"app": app, "push_footer": push_footer}

        disposers = cc_dump.view_store.setup_reactions(store, context)

        push_footer.reset_mock()
        store.set("filter:active", "2")

        push_footer.assert_called()
        state = push_footer.call_args[0][0]
        assert state["active_filterset"] == "2"


class TestErrorReaction:
    def test_error_reaction_fires_on_exception_append(self):
        import cc_dump.tui.error_indicator
        ErrorItem = cc_dump.tui.error_indicator.ErrorItem
        store = cc_dump.view_store.create()
        app = MagicMock()
        app.is_running = True
        app._rerender_if_mounted = MagicMock()
        push_errors = MagicMock()
        context = {"app": app, "push_errors": push_errors}

        disposers = cc_dump.view_store.setup_reactions(store, context)
        push_errors.reset_mock()

        store.exception_items.append(ErrorItem("exc-1", "\U0001f4a5", "RuntimeError: boom"))

        push_errors.assert_called()
        items = push_errors.call_args[0][0]
        assert len(items) == 1
        assert items[0].summary == "RuntimeError: boom"
