"""Tests for view_store — reactive category visibility state."""

from unittest.mock import MagicMock

import pytest

import cc_dump.view_store
from cc_dump.formatting import VisState
from cc_dump.tui.category_config import CATEGORY_CONFIG
from snarfx import autorun, transaction


class TestSchema:
    def test_schema_has_18_keys(self):
        assert len(cc_dump.view_store.SCHEMA) == 18  # 6 categories × 3 axes

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
