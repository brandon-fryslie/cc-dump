"""Tests for `run` subcommand parsing in cli.py."""

from pathlib import Path
import re

import pytest

from cc_dump.app.launch_config import LaunchConfig
from cc_dump.cli import (
    _detect_run_subcommand,
    _resolve_auto_launch_config_name,
    _recordings_output_dir,
    _recording_path,
)
from cc_dump.cli_presentation import render_recordings_list


class TestDetectRunSubcommand:
    def test_no_run_keyword(self):
        name, flags, extra = _detect_run_subcommand(["--port", "5000"])
        assert name is None
        assert flags == ["--port", "5000"]
        assert extra == []

    def test_empty_argv(self):
        name, flags, extra = _detect_run_subcommand([])
        assert name is None
        assert flags == []
        assert extra == []

    def test_run_config_only(self):
        name, flags, extra = _detect_run_subcommand(["run", "claude"])
        assert name == "claude"
        assert flags == []
        assert extra == []

    def test_run_with_cc_dump_flags(self):
        name, flags, extra = _detect_run_subcommand(["run", "claude", "--port", "5000"])
        assert name == "claude"
        assert flags == ["--port", "5000"]
        assert extra == []

    def test_run_with_separator_and_extra_args(self):
        name, flags, extra = _detect_run_subcommand(["run", "claude", "--", "--continue"])
        assert name == "claude"
        assert flags == []
        assert extra == ["--continue"]

    def test_run_with_cc_dump_flags_and_extra_args(self):
        name, flags, extra = _detect_run_subcommand(
            ["run", "claude", "--port", "5000", "--", "--continue", "--verbose"]
        )
        assert name == "claude"
        assert flags == ["--port", "5000"]
        assert extra == ["--continue", "--verbose"]

    def test_run_no_config_name_exits(self):
        with pytest.raises(SystemExit) as exc:
            _detect_run_subcommand(["run"])
        assert exc.value.code == 0

    def test_run_help_exits(self):
        with pytest.raises(SystemExit) as exc:
            _detect_run_subcommand(["run", "--help"])
        assert exc.value.code == 0

    def test_run_short_help_exits(self):
        with pytest.raises(SystemExit) as exc:
            _detect_run_subcommand(["run", "-h"])
        assert exc.value.code == 0

    def test_separator_only_no_extra(self):
        name, flags, extra = _detect_run_subcommand(["run", "claude", "--"])
        assert name == "claude"
        assert flags == []
        assert extra == []

    def test_multiple_extra_args(self):
        name, flags, extra = _detect_run_subcommand(
            ["run", "haiku", "--", "-a", "-b", "--flag", "val"]
        )
        assert name == "haiku"
        assert flags == []
        assert extra == ["-a", "-b", "--flag", "val"]

    def test_flags_before_run(self):
        name, flags, extra = _detect_run_subcommand(
            ["--upstream", "copilot", "run", "claude"]
        )
        assert name == "claude"
        assert flags == ["--upstream", "copilot"]
        assert extra == []

    def test_flags_before_and_after_run(self):
        name, flags, extra = _detect_run_subcommand(
            ["--upstream", "copilot", "run", "claude", "--port", "5000"]
        )
        assert name == "claude"
        assert flags == ["--upstream", "copilot", "--port", "5000"]
        assert extra == []

    def test_flags_before_run_with_extra_args(self):
        name, flags, extra = _detect_run_subcommand(
            ["--upstream", "copilot", "run", "claude", "--", "--dangerously-bypass-permissions"]
        )
        assert name == "claude"
        assert flags == ["--upstream", "copilot"]
        assert extra == ["--dangerously-bypass-permissions"]


class TestResolveAutoLaunchConfigName:
    def test_none_passthrough(self):
        assert _resolve_auto_launch_config_name(None) is None

    def test_existing_config_name_returns_name(self, monkeypatch):
        monkeypatch.setattr(
            "cc_dump.app.launch_config.load_configs",
            lambda: [LaunchConfig(name="claude"), LaunchConfig(name="haiku")],
        )
        assert _resolve_auto_launch_config_name("haiku") == "haiku"

    def test_unknown_config_name_exits(self, monkeypatch):
        monkeypatch.setattr(
            "cc_dump.app.launch_config.load_configs",
            lambda: [LaunchConfig(name="claude"), LaunchConfig(name="haiku")],
        )
        with pytest.raises(SystemExit) as excinfo:
            _resolve_auto_launch_config_name("missing")
        assert excinfo.value.code == 2


class TestRecordingPathHelpers:
    def test_recordings_output_dir_defaults_to_user_recordings_root(self):
        output = _recordings_output_dir(None)
        assert output == Path.home() / ".local" / "share" / "cc-dump" / "recordings"

    def test_recordings_output_dir_file_arg_uses_parent_directory(self):
        output = _recordings_output_dir("/tmp/custom.har")
        assert output == Path("/tmp")

    def test_recordings_output_dir_existing_har_suffixed_directory_is_preserved(self, tmp_path):
        directory = tmp_path / "recordings.har"
        directory.mkdir()
        output = _recordings_output_dir(str(directory))
        assert output == directory

    def test_recording_path_uses_timestamp_format(self):
        timestamp = "20260304-231500Z"
        path = _recording_path(Path("/tmp/recordings"), timestamp)
        assert path.startswith("/tmp/recordings/ccdump-20260304-231500Z-")
        assert path.endswith(".har")
        short_id = Path(path).stem.rsplit("-", 1)[-1]
        assert re.fullmatch(r"[0-9a-f]{8}", short_id) is not None


class TestRenderRecordingsList:
    def test_render_empty(self):
        assert render_recordings_list([]) == "No recordings found.\n"

    def test_render_single_recording_row(self):
        output = render_recordings_list([
            {
                "path": "/tmp/recording-a.har",
                "filename": "recording-a.har",
                "session_id": "a",
                "session_name": "session-a",
                "provider": "anthropic",
                "created": "2026-03-04T12:34:56.000000+00:00",
                "entry_count": 3,
                "size_bytes": 1024,
            }
        ])
        assert "Found 1 recording(s):" in output
        assert "SESSION" in output
        assert "session-a" in output
        assert "anthropic" in output
        assert "2026-03-04 12:34:56" in output
