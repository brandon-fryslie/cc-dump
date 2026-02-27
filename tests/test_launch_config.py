"""Tests for launch_config module — serialization, command building, fallback behavior."""

import json

import pytest

from cc_dump.app.launch_config import (
    LaunchConfig,
    build_full_command,
    build_launch_profile,
    default_configs,
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

    monkeypatch.setattr("cc_dump.io.settings.get_config_path", _get_config_path)
    return settings_path


class TestSerialization:
    """Round-trip save/load of configs."""

    def test_default_configs_when_no_file(self, settings_file):
        """Missing settings file returns one default config per launcher."""
        configs = load_configs()
        names = [config.name for config in configs]
        assert names == ["claude", "copilot"]

        claude = configs[0]
        copilot = configs[1]
        assert claude.launcher == "claude"
        assert claude.resolved_command == "claude"
        assert claude.options["auto_resume"] is True
        assert claude.options["extra_args"] == ""

        assert copilot.launcher == "copilot"
        assert copilot.resolved_command == "copilot"
        assert copilot.options["yolo"] is False

    def test_round_trip(self, settings_file):
        """Save and reload preserves all fields and per-tool options."""
        configs = [
            LaunchConfig(
                name="claude",
                launcher="claude",
                command="clod",
                model="haiku",
                options={
                    "auto_resume": False,
                    "bypass": True,
                    "continue": True,
                    "extra_args": "--verbose",
                },
            ),
            LaunchConfig(
                name="copilot",
                launcher="copilot",
                command="",
                model="ignored",
                options={"extra_args": "--json", "yolo": True},
            ),
        ]
        save_configs(configs)

        loaded = load_configs()
        assert len(loaded) == 2

        claude = loaded[0]
        assert claude.name == "claude"
        assert claude.launcher == "claude"
        assert claude.command == "clod"
        assert claude.model == "haiku"
        assert claude.options["auto_resume"] is False
        assert claude.options["bypass"] is True
        assert claude.options["continue"] is True
        assert claude.options["extra_args"] == "--verbose"

        copilot = loaded[1]
        assert copilot.name == "copilot"
        assert copilot.launcher == "copilot"
        assert copilot.command == ""
        assert copilot.resolved_command == "copilot"
        assert copilot.options["yolo"] is True
        assert copilot.options["extra_args"] == "--json"

    def test_empty_list_falls_back_to_tool_defaults(self, settings_file):
        """Saving empty list, reloading gives default tool presets."""
        save_configs([])
        loaded = load_configs()
        assert [config.name for config in loaded] == ["claude", "copilot"]

    def test_corrupt_data_falls_back_to_tool_defaults(self, settings_file):
        """Non-list data in settings falls back to defaults."""
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(json.dumps({"launch_configs": "bad"}))

        loaded = load_configs()
        assert [config.name for config in loaded] == ["claude", "copilot"]

    def test_missing_tool_default_is_auto_added(self, settings_file):
        """Persisted configs always include canonical tool-named presets."""
        save_configs([LaunchConfig(name="custom", launcher="claude")])
        loaded = load_configs()
        names = [config.name for config in loaded]
        assert "claude" in names
        assert "copilot" in names


class TestActiveName:
    """Active config name persistence."""

    def test_default_active_name(self, settings_file):
        """Default active name is the default launcher key."""
        assert load_active_name() == "claude"

    def test_save_and_load_active_name(self, settings_file):
        """Save then load preserves name."""
        save_active_name("haiku-fast")
        assert load_active_name() == "haiku-fast"


class TestGetActiveConfig:
    """Lookup by name with fallback."""

    def test_finds_by_name(self, settings_file):
        """Returns config matching active name."""
        configs = [
            LaunchConfig(name="claude", launcher="claude"),
            LaunchConfig(name="haiku-fast", launcher="claude", model="haiku"),
            LaunchConfig(name="copilot", launcher="copilot"),
        ]
        save_configs(configs)
        save_active_name("haiku-fast")

        active = get_active_config()
        assert active.name == "haiku-fast"
        assert active.model == "haiku"

    def test_falls_back_to_first(self, settings_file):
        """If active name doesn't match any config, returns first."""
        configs = [
            LaunchConfig(name="alpha", launcher="claude", model="opus"),
            LaunchConfig(name="beta", launcher="copilot"),
        ]
        save_configs(configs)
        save_active_name("nonexistent")

        active = get_active_config()
        assert active.name == "alpha"

    def test_default_with_no_settings(self, settings_file):
        """No settings file at all returns default launcher config."""
        active = get_active_config()
        assert active.name == "claude"


class TestBuildFullCommand:
    """Full command assembly from config + session_id."""

    def test_empty_config(self):
        """Default config with no session produces default launcher command."""
        config = LaunchConfig()
        assert build_full_command(config) == "claude"

    def test_custom_command(self):
        """Config with custom command uses it."""
        config = LaunchConfig(command="clod")
        assert build_full_command(config) == "clod"

    def test_model_only_for_claude(self):
        """Claude launcher accepts --model."""
        config = LaunchConfig(model="haiku")
        assert build_full_command(config) == "claude --model haiku"

    def test_resume_with_session_for_claude(self):
        """Claude launcher adds --resume when auto_resume is enabled."""
        config = LaunchConfig(options={"auto_resume": True})
        result = build_full_command(config, session_id="abc-123")
        assert "--resume abc-123" in result

    def test_resume_without_session(self):
        """auto_resume=True but empty session_id omits --resume."""
        config = LaunchConfig(options={"auto_resume": True})
        result = build_full_command(config, session_id="")
        assert "--resume" not in result

    def test_resume_disabled(self):
        """auto_resume=False omits --resume even with session_id."""
        config = LaunchConfig(options={"auto_resume": False})
        result = build_full_command(config, session_id="abc-123")
        assert "--resume" not in result

    def test_extra_args(self):
        """Common extra args are appended."""
        config = LaunchConfig(options={"extra_args": "--verbose --no-cache"})
        assert build_full_command(config) == "claude --verbose --no-cache"

    def test_claude_specific_flags(self):
        """Claude bypass/continue flags are injected when enabled."""
        config = LaunchConfig(
            model="opus",
            options={
                "extra_args": "--verbose",
                "auto_resume": True,
                "bypass": True,
                "continue": True,
            },
        )
        result = build_full_command(config, session_id="sess-42")
        assert (
            result
            == "claude --model opus --verbose --resume sess-42 --dangerously-bypass-permissions --continue"
        )

    def test_copilot_includes_yolo_but_ignores_resume_and_model(self):
        """Copilot launcher only receives compatible options."""
        config = LaunchConfig(
            launcher="copilot",
            command="copilot",
            model="ignored",
            options={
                "extra_args": "--json",
                "auto_resume": True,
                "yolo": True,
            },
        )
        result = build_full_command(config, session_id="sess-1")
        assert result == "copilot --json --yolo"


class TestBuildLaunchProfile:
    def test_profile_sets_provider_env_for_copilot(self):
        config = LaunchConfig(launcher="copilot", command="")
        endpoints = {
            "copilot": {"proxy_url": "http://127.0.0.1:4567", "target": "https://api.githubcopilot.com"}
        }
        profile = build_launch_profile(config, provider_endpoints=endpoints, session_id="")
        assert profile.launcher_key == "copilot"
        assert profile.command == "copilot"
        assert profile.environment == {"COPILOT_BASE_URL": "http://127.0.0.1:4567"}
        assert "copilot" in profile.process_names


class TestDefaultsFactory:
    def test_default_configs_match_registered_launchers(self):
        configs = default_configs()
        assert [config.name for config in configs] == ["claude", "copilot"]
