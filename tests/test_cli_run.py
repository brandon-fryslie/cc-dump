"""Tests for `run` subcommand parsing in cli.py."""

import pytest

from cc_dump.cli import _detect_run_subcommand


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
