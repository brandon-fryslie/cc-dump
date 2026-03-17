"""Tests for settings_store — reactive settings with persistence and consumer sync."""

import json

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
        assert store.get("theme") is None

    def test_seeds_from_disk(self, tmp_settings):
        tmp_settings.write_text(json.dumps({
            "theme": "gruvbox",
        }))
        store = cc_dump.app.settings_store.create()
        assert store.get("theme") == "gruvbox"

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
        autorun(lambda: log.append(store.get("theme")))
        assert log == [None]
        store.update({"theme": "y"})
        # Single batch, not two separate updates
        assert log == [None, "y"]
