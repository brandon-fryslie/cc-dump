"""Tests for launch_config module — serialization, command building, fallback behavior."""

import json

import pytest

from cc_dump.launch_config import (
    LaunchConfig,
    build_full_command,
    get_active_config,
    load_active_name,
    load_configs,
    save_active_name,
    save_configs,
)


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Redirect settings to a temp file and return its path."""
    settings_path = tmp_path / "cc-dump" / "settings.json"

    def _get_config_path():
        return settings_path

    monkeypatch.setattr("cc_dump.settings.get_config_path", _get_config_path)
    return settings_path


class TestSerialization:
    """Round-trip save/load of configs."""

    def test_default_config_when_no_file(self, settings_file):
        """Missing settings file returns [default] config."""
        configs = load_configs()
        assert len(configs) == 1
        assert configs[0].name == "default"
        assert configs[0].auto_resume is True
        assert configs[0].claude_command == "claude"

    def test_round_trip(self, settings_file):
        """Save and reload preserves all fields."""
        configs = [
            LaunchConfig(name="fast", claude_command="clod", model="haiku", auto_resume=False, extra_flags="--verbose"),
            LaunchConfig(name="debug", model="opus", auto_resume=True, extra_flags=""),
        ]
        save_configs(configs)

        loaded = load_configs()
        assert len(loaded) == 2
        assert loaded[0].name == "fast"
        assert loaded[0].claude_command == "clod"
        assert loaded[0].model == "haiku"
        assert loaded[0].auto_resume is False
        assert loaded[0].extra_flags == "--verbose"
        assert loaded[1].name == "debug"
        assert loaded[1].claude_command == "claude"
        assert loaded[1].model == "opus"
        assert loaded[1].auto_resume is True

    def test_empty_list_falls_back_to_default(self, settings_file):
        """Saving empty list, reloading gives [default]."""
        save_configs([])
        loaded = load_configs()
        assert len(loaded) == 1
        assert loaded[0].name == "default"

    def test_corrupt_data_falls_back_to_default(self, settings_file):
        """Non-list data in settings falls back to [default]."""
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(json.dumps({"launch_configs": "bad"}))

        loaded = load_configs()
        assert len(loaded) == 1
        assert loaded[0].name == "default"


class TestActiveName:
    """Active config name persistence."""

    def test_default_active_name(self, settings_file):
        """Default active name is 'default'."""
        assert load_active_name() == "default"

    def test_save_and_load_active_name(self, settings_file):
        """Save then load preserves name."""
        save_active_name("haiku-fast")
        assert load_active_name() == "haiku-fast"


class TestGetActiveConfig:
    """Lookup by name with fallback."""

    def test_finds_by_name(self, settings_file):
        """Returns config matching active name."""
        configs = [
            LaunchConfig(name="default"),
            LaunchConfig(name="haiku-fast", model="haiku"),
        ]
        save_configs(configs)
        save_active_name("haiku-fast")

        active = get_active_config()
        assert active.name == "haiku-fast"
        assert active.model == "haiku"

    def test_falls_back_to_first(self, settings_file):
        """If active name doesn't match any config, returns first."""
        configs = [
            LaunchConfig(name="alpha", model="opus"),
            LaunchConfig(name="beta"),
        ]
        save_configs(configs)
        save_active_name("nonexistent")

        active = get_active_config()
        assert active.name == "alpha"

    def test_default_with_no_settings(self, settings_file):
        """No settings file at all returns default config."""
        active = get_active_config()
        assert active.name == "default"


class TestBuildFullCommand:
    """Full command assembly from config.claude_command + session_id."""

    def test_empty_config(self):
        """Default config with no session produces just the claude command."""
        config = LaunchConfig()
        assert build_full_command(config) == "claude"

    def test_custom_command(self):
        """Config with custom claude_command uses it."""
        config = LaunchConfig(claude_command="clod")
        assert build_full_command(config) == "clod"

    def test_model_only(self):
        """Config with model produces --model flag."""
        config = LaunchConfig(model="haiku")
        assert build_full_command(config) == "claude --model haiku"

    def test_resume_with_session(self):
        """auto_resume=True + session_id produces --resume flag."""
        config = LaunchConfig(auto_resume=True)
        result = build_full_command(config, session_id="abc-123")
        assert "--resume abc-123" in result

    def test_resume_without_session(self):
        """auto_resume=True but empty session_id omits --resume."""
        config = LaunchConfig(auto_resume=True)
        result = build_full_command(config, session_id="")
        assert "--resume" not in result

    def test_resume_disabled(self):
        """auto_resume=False omits --resume even with session_id."""
        config = LaunchConfig(auto_resume=False)
        result = build_full_command(config, session_id="abc-123")
        assert "--resume" not in result

    def test_extra_flags(self):
        """Extra flags are appended."""
        config = LaunchConfig(extra_flags="--verbose --no-cache")
        assert build_full_command(config) == "claude --verbose --no-cache"

    def test_all_combined(self):
        """Model + resume + extra flags all present."""
        config = LaunchConfig(
            model="opus",
            auto_resume=True,
            extra_flags="--verbose",
        )
        result = build_full_command(config, session_id="sess-42")
        assert result == "claude --model opus --resume sess-42 --verbose"

    def test_custom_command_all_combined(self):
        """Custom command + model + resume + extra flags."""
        config = LaunchConfig(
            claude_command="clod",
            model="haiku",
            auto_resume=True,
            extra_flags="--fast",
        )
        result = build_full_command(config, session_id="sess-1")
        assert result == "clod --model haiku --resume sess-1 --fast"
