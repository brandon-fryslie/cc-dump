"""Tests for view_store — reactive category visibility + panel/follow state."""

from unittest.mock import MagicMock

import pytest

import cc_dump.view_store
from cc_dump.formatting import VisState
from cc_dump.tui.category_config import CATEGORY_CONFIG
from snarfx import autorun, transaction


class TestSchema:
    def test_schema_has_23_keys(self):
        # 6 categories × 3 axes + 5 panel/follow keys
        assert len(cc_dump.view_store.SCHEMA) == 23

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
        assert hasattr(store, "active_filters")
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
        assert cc_dump.view_store.SCHEMA["follow"] == "active"

    def test_store_has_panel_keys(self):
        store = cc_dump.view_store.create()
        assert store.get("panel:active") == "session"
        assert store.get("panel:side_channel") is False
        assert store.get("panel:settings") is False
        assert store.get("panel:launch_config") is False
        assert store.get("follow") == "active"

    def test_panel_active_set_and_get(self):
        store = cc_dump.view_store.create()
        store.set("panel:active", "stats")
        assert store.get("panel:active") == "stats"

    def test_follow_set_and_get(self):
        store = cc_dump.view_store.create()
        store.set("follow", "off")
        assert store.get("follow") == "off"


class TestPanelActiveReaction:
    def test_reaction_fires_on_panel_change(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app.is_running = True
        app._replacing_widgets = False
        app._rerender_if_mounted = MagicMock()
        app._sync_panel_display = MagicMock()
        app._update_footer_state = MagicMock()
        context = {"app": app}

        disposers = cc_dump.view_store.setup_reactions(store, context)

        app._sync_panel_display.reset_mock()
        app._update_footer_state.reset_mock()

        store.set("panel:active", "stats")

        app._sync_panel_display.assert_called_with("stats")
        app._update_footer_state.assert_called()

    def test_reaction_guarded_during_widget_replacement(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app.is_running = True
        app._replacing_widgets = True
        app._rerender_if_mounted = MagicMock()
        app._sync_panel_display = MagicMock()
        context = {"app": app}

        disposers = cc_dump.view_store.setup_reactions(store, context)
        app._sync_panel_display.reset_mock()

        store.set("panel:active", "timeline")

        app._sync_panel_display.assert_not_called()

    def test_reaction_guarded_before_running(self):
        store = cc_dump.view_store.create()
        app = MagicMock()
        app.is_running = False
        app._replacing_widgets = False
        app._rerender_if_mounted = MagicMock()
        app._sync_panel_display = MagicMock()
        context = {"app": app}

        disposers = cc_dump.view_store.setup_reactions(store, context)
        app._sync_panel_display.reset_mock()

        store.set("panel:active", "economics")

        app._sync_panel_display.assert_not_called()


class TestReconcileWithNewKeys:
    def test_reconcile_preserves_panel_values(self):
        store = cc_dump.view_store.create()
        store.set("panel:active", "timeline")
        store.set("follow", "off")

        store.reconcile(cc_dump.view_store.SCHEMA, lambda s: [])

        assert store.get("panel:active") == "timeline"
        assert store.get("follow") == "off"

    def test_reconcile_adds_new_keys_with_defaults(self):
        """First reconcile after Phase 3 adds 5 keys with defaults."""
        store = cc_dump.view_store.create()
        # Simulate reconcile (which normally happens after hot-reload)
        store.reconcile(cc_dump.view_store.SCHEMA, lambda s: [])

        # All keys present with defaults
        assert store.get("panel:active") == "session"
        assert store.get("panel:side_channel") is False
        assert store.get("follow") == "active"
