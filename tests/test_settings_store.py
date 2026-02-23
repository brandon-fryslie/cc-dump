"""Tests for settings_store — reactive settings with persistence and consumer sync."""

import json
from unittest.mock import MagicMock

import pytest

import cc_dump.app.settings_store
from snarfx import autorun


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """Redirect settings file to a temp directory."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(
        "cc_dump.io.settings.get_config_path",
        lambda: settings_file,
    )
    return settings_file


class TestCreate:
    def test_creates_store_with_schema_defaults(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        assert store.get("auto_zoom_default") is False
        assert store.get("side_channel_enabled") is True
        assert store.get("side_channel_global_kill") is False
        assert store.get("side_channel_max_concurrent") == 1
        assert store.get("side_channel_purpose_enabled") == {}
        assert store.get("side_channel_timeout_by_purpose") == {}
        assert store.get("side_channel_budget_caps") == {}
        assert store.get("theme") is None

    def test_seeds_from_disk(self, tmp_settings):
        tmp_settings.write_text(json.dumps({
            "theme": "gruvbox",
        }))
        store = cc_dump.app.settings_store.create()
        assert store.get("theme") == "gruvbox"
        # Unset keys get schema defaults
        assert store.get("auto_zoom_default") is False

    def test_initial_overrides(self, tmp_settings):
        store = cc_dump.app.settings_store.create(initial_overrides={"theme": "dark"})
        assert store.get("theme") == "dark"

    def test_disk_overrides_schema_but_initial_overrides_disk(self, tmp_settings):
        tmp_settings.write_text(json.dumps({"theme": "from-disk"}))
        store = cc_dump.app.settings_store.create(initial_overrides={"theme": "override"})
        assert store.get("theme") == "override"


class TestSetupReactions:
    def test_persistence_reaction(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        disposers = cc_dump.app.settings_store.setup_reactions(store)
        store._reaction_disposers = disposers

        store.set("theme", "custom-theme")

        data = json.loads(tmp_settings.read_text())
        assert data["theme"] == "custom-theme"

    def test_side_channel_sync(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        mgr = MagicMock()
        mgr.enabled = True
        mgr.global_kill = False
        context = {"side_channel_manager": mgr}
        disposers = cc_dump.app.settings_store.setup_reactions(store, context)
        store._reaction_disposers = disposers

        # fire_immediately syncs initial value
        assert mgr.enabled is True
        assert mgr.global_kill is False

        store.set("side_channel_enabled", False)
        assert mgr.enabled is False
        store.set("side_channel_global_kill", True)
        assert mgr.global_kill is True
        store.set("side_channel_max_concurrent", 3)
        mgr.set_max_concurrent.assert_called_with(3)
        mgr.set_purpose_enabled_map.assert_called_with({})
        mgr.set_timeout_overrides.assert_called_with({})
        mgr.set_budget_caps.assert_called_with({})

    def test_tmux_auto_zoom_sync(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        tmux = MagicMock()
        tmux.auto_zoom = False
        context = {"tmux_controller": tmux}
        disposers = cc_dump.app.settings_store.setup_reactions(store, context)
        store._reaction_disposers = disposers

        store.set("auto_zoom_default", True)
        assert tmux.auto_zoom is True

    def test_no_context_still_persists(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        disposers = cc_dump.app.settings_store.setup_reactions(store)
        store._reaction_disposers = disposers

        store.set("theme", "gruvbox")
        data = json.loads(tmp_settings.read_text())
        assert data["theme"] == "gruvbox"


class TestReconcile:
    def test_reconcile_preserves_values(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        store.set("theme", "preserved-theme")

        store.reconcile(
            cc_dump.app.settings_store.SCHEMA,
            lambda s: cc_dump.app.settings_store.setup_reactions(s),
        )
        assert store.get("theme") == "preserved-theme"

    def test_reconcile_adds_new_keys(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        extended_schema = {**cc_dump.app.settings_store.SCHEMA, "new_key": "default_val"}

        store.reconcile(extended_schema, lambda s: [])
        assert store.get("new_key") == "default_val"

    def test_reconcile_re_registers_reactions(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        disposers = cc_dump.app.settings_store.setup_reactions(store)
        store._reaction_disposers = disposers

        store.set("theme", "first")
        data1 = json.loads(tmp_settings.read_text())
        assert data1["theme"] == "first"

        # Reconcile re-registers
        store.reconcile(
            cc_dump.app.settings_store.SCHEMA,
            lambda s: cc_dump.app.settings_store.setup_reactions(s),
        )
        store.set("theme", "second")
        data2 = json.loads(tmp_settings.read_text())
        assert data2["theme"] == "second"


class TestReactiveTracking:
    def test_autorun_tracks_store_gets(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        log = []
        autorun(lambda: log.append(store.get("theme")))
        assert log == [None]
        store.set("theme", "dark")
        assert log == [None, "dark"]

    def test_update_batches(self, tmp_settings):
        store = cc_dump.app.settings_store.create()
        log = []
        autorun(lambda: log.append((store.get("auto_zoom_default"), store.get("theme"))))
        assert log == [(False, None)]
        store.update({"auto_zoom_default": True, "theme": "y"})
        # Single batch, not two separate updates
        assert log == [(False, None), (True, "y")]
