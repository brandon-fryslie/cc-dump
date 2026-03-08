"""Tests for settings I/O helpers."""

import json

import pytest

import cc_dump.io.settings


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """Redirect settings file to a temp directory."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(
        "cc_dump.io.settings.get_config_path",
        lambda: settings_file,
    )
    return settings_file


def test_merge_setting_returns_new_dict():
    original = {"theme": "dark"}
    merged = cc_dump.io.settings.merge_setting(original, "side_channel_enabled", False)
    assert merged == {"theme": "dark", "side_channel_enabled": False}
    assert original == {"theme": "dark"}
    assert merged is not original


def test_save_setting_merges_into_existing(tmp_settings):
    tmp_settings.write_text(json.dumps({"theme": "gruvbox"}))
    cc_dump.io.settings.save_setting("side_channel_enabled", False)

    data = json.loads(tmp_settings.read_text())
    assert data["theme"] == "gruvbox"
    assert data["side_channel_enabled"] is False
