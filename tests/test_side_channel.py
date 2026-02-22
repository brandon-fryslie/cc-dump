"""Tests for side-channel manager and data dispatcher."""

from __future__ import annotations

import subprocess
import threading
import time
from unittest.mock import patch, MagicMock

from cc_dump.side_channel import SideChannelManager, SideChannelResult
from cc_dump.data_dispatcher import DataDispatcher


# ─── SideChannelManager tests ────────────────────────────────────────


class TestSideChannelManager:
    """Tests for SideChannelManager subprocess handling."""

    def test_query_success(self):
        """Successful claude -p invocation returns text."""
        mgr = SideChannelManager(claude_command="claude")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  This is a summary.  \n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = mgr.query("Summarize this")

        assert result.text == "This is a summary."
        assert result.error is None
        assert result.elapsed_ms >= 0
        assert result.policy_version == "redaction-v1"
        # Verify subprocess args
        args = mock_run.call_args
        assert args[0][0] == [
            "claude",
            "-p",
            "--model",
            "haiku",
            "--tools",
            "",
            "--no-session-persistence",
        ]
        assert "Summarize this" in args[1]["input"]
        assert "CC_DUMP_SIDE_CHANNEL" in args[1]["input"]
        assert '"prompt_version":"v1"' in args[1]["input"]
        assert '"policy_version":"redaction-v1"' in args[1]["input"]
        assert args[1]["capture_output"] is True
        assert args[1]["text"] is True

    def test_query_nonzero_exit(self):
        """Nonzero exit code returns error with stderr."""
        mgr = SideChannelManager()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Some error occurred"

        with patch("subprocess.run", return_value=mock_result):
            result = mgr.query("test")

        assert result.text == ""
        assert "Exit code 1" in result.error
        assert "Some error occurred" in result.error

    def test_query_timeout(self):
        """Timeout returns error."""
        mgr = SideChannelManager()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 30)):
            result = mgr.query("test", timeout=30)

        assert result.text == ""
        assert "Timeout" in result.error

    def test_query_command_not_found(self):
        """Missing command returns error."""
        mgr = SideChannelManager(claude_command="nonexistent-claude")

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = mgr.query("test")

        assert result.text == ""
        assert "Command not found" in result.error
        assert "nonexistent-claude" in result.error

    def test_enabled_property(self):
        """Enabled can be toggled."""
        mgr = SideChannelManager()
        assert mgr.enabled is True

        mgr.enabled = False
        assert mgr.enabled is False

    def test_set_claude_command(self):
        """Claude command can be updated."""
        mgr = SideChannelManager(claude_command="claude")
        mgr.set_claude_command("/usr/local/bin/claude")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            mgr.query("test")

        assert mock_run.call_args[0][0][0] == "/usr/local/bin/claude"

    def test_query_empty_stderr_on_error(self):
        """Nonzero exit with no stderr shows fallback message."""
        mgr = SideChannelManager()
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = mgr.query("test")

        assert "(no stderr)" in result.error

    def test_global_kill_switch_blocks_run(self):
        mgr = SideChannelManager()
        mgr.global_kill = True
        result = mgr.query("test")
        assert "kill switch" in str(result.error).lower()

    def test_profile_resume_uses_resume_and_fork_flags(self):
        mgr = SideChannelManager()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _ = mgr.run(
                prompt="test",
                purpose="block_summary",
                source_session_id="123e4567-e89b-12d3-a456-426614174000",
                profile="cache_probe_resume",
            )
        cmd = mock_run.call_args[0][0]
        assert "--resume" in cmd
        assert "--fork-session" in cmd

    def test_unknown_purpose_normalized_to_utility_custom(self):
        mgr = SideChannelManager()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = mgr.run(
                prompt="test",
                purpose="nonexistent_purpose",
                source_session_id="",
                profile="ephemeral_default",
            )
        assert result.purpose == "utility_custom"

    def test_guardrail_blocks_disabled_purpose(self):
        mgr = SideChannelManager()
        mgr.set_purpose_enabled_map({"block_summary": False})
        result = mgr.run(
            prompt="test",
            purpose="block_summary",
            profile="ephemeral_default",
        )
        assert result.error is not None
        assert "Guardrail" in result.error
        assert "purpose disabled" in result.error

    def test_guardrail_budget_cap_blocks_run(self):
        mgr = SideChannelManager()
        mgr.set_budget_caps({"block_summary": 10})
        mgr.set_usage_provider(
            lambda _purpose: {
                "input_tokens": 6,
                "cache_read_tokens": 2,
                "cache_creation_tokens": 0,
                "output_tokens": 3,
            }
        )
        with patch("subprocess.run") as mock_run:
            result = mgr.run(
                prompt="test",
                purpose="block_summary",
                profile="ephemeral_default",
            )
        assert result.error is not None
        assert "Guardrail:" in result.error
        assert "budget cap reached" in result.error
        mock_run.assert_not_called()

    def test_run_uses_per_purpose_default_timeout_when_not_provided(self):
        mgr = SideChannelManager()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _ = mgr.run(
                prompt="test",
                purpose="core_debug_lane",
                timeout=None,
                profile="ephemeral_default",
            )
        assert mock_run.call_args.kwargs["timeout"] == 30

    def test_run_uses_timeout_override_and_clamps_max(self):
        mgr = SideChannelManager()
        mgr.set_timeout_overrides({"block_summary": 7})
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _ = mgr.run(
                prompt="test",
                purpose="block_summary",
                timeout=None,
                profile="ephemeral_default",
            )
        assert mock_run.call_args.kwargs["timeout"] == 7

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _ = mgr.run(
                prompt="test",
                purpose="block_summary",
                timeout=9999,
                profile="ephemeral_default",
            )
        assert mock_run.call_args.kwargs["timeout"] == 120

    def test_max_concurrent_enforced(self):
        mgr = SideChannelManager()
        mgr.set_max_concurrent(1)
        active = 0
        max_active = 0
        lock = threading.Lock()

        def _slow_run(*_args, **_kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return MagicMock(returncode=0, stdout="ok", stderr="")

        with patch("subprocess.run", side_effect=_slow_run):
            threads = [
                threading.Thread(
                    target=lambda: mgr.run(
                        prompt="x", purpose="block_summary", profile="ephemeral_default"
                    )
                )
                for _ in range(3)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        assert max_active == 1

    def test_manager_applies_redaction_boundary_before_dispatch(self):
        mgr = SideChannelManager()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _ = mgr.run(
                prompt="authorization: Bearer SECRET_TOKEN_123",
                purpose="block_summary",
                profile="ephemeral_default",
            )
        sent_prompt = str(mock_run.call_args.kwargs["input"])
        assert "SECRET_TOKEN_123" not in sent_prompt
        assert "[REDACTED]" in sent_prompt


# ─── DataDispatcher tests ────────────────────────────────────────────


class TestDataDispatcher:
    """Tests for DataDispatcher routing and fallback."""

    def _make_dispatcher(self, enabled=True, query_result=None):
        """Helper to create a dispatcher with a mock side-channel."""
        mgr = SideChannelManager()
        mgr.enabled = enabled
        if query_result is not None:
            mgr.run = MagicMock(return_value=query_result)
        return DataDispatcher(mgr), mgr

    def test_summarize_when_enabled(self):
        """Enabled dispatcher routes to AI."""
        result = SideChannelResult(text="AI summary here", error=None, elapsed_ms=500)
        dispatcher, mgr = self._make_dispatcher(enabled=True, query_result=result)

        messages = [{"role": "user", "content": "hello"}]
        enriched = dispatcher.summarize_messages(messages)

        assert enriched.source == "ai"
        assert enriched.text == "AI summary here"
        assert enriched.elapsed_ms == 500
        mgr.run.assert_called_once()
        call = mgr.run.call_args
        assert call.kwargs["prompt_version"] == "v1"

    def test_summarize_when_disabled(self):
        """Disabled dispatcher returns fallback without calling AI."""
        dispatcher, mgr = self._make_dispatcher(enabled=False)
        mgr.run = MagicMock()

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        enriched = dispatcher.summarize_messages(messages)

        assert enriched.source == "fallback"
        assert "2 messages" in enriched.text
        assert "1 assistant" in enriched.text
        assert "1 user" in enriched.text
        assert enriched.elapsed_ms == 0
        mgr.run.assert_not_called()

    def test_summarize_on_error(self):
        """AI error returns error text with fallback appended."""
        result = SideChannelResult(text="", error="Timeout (60s)", elapsed_ms=60000)
        dispatcher, _ = self._make_dispatcher(enabled=True, query_result=result)

        messages = [{"role": "user", "content": "hello"}]
        enriched = dispatcher.summarize_messages(messages)

        assert enriched.source == "error"
        assert "Timeout (60s)" in enriched.text
        assert "1 messages" in enriched.text  # fallback appended

    def test_summarize_guardrail_error_returns_fallback_source(self):
        result = SideChannelResult(
            text="",
            error="Guardrail: budget cap reached for block_summary: used=120 cap=100",
            elapsed_ms=0,
        )
        dispatcher, _ = self._make_dispatcher(enabled=True, query_result=result)
        messages = [{"role": "user", "content": "hello"}]
        enriched = dispatcher.summarize_messages(messages)
        assert enriched.source == "fallback"
        assert "side-channel blocked" in enriched.text
        assert "1 messages" in enriched.text

    def test_fallback_summary_empty(self):
        """Empty message list produces appropriate fallback."""
        dispatcher, _ = self._make_dispatcher(enabled=False)

        enriched = dispatcher.summarize_messages([])

        assert enriched.source == "fallback"
        assert "No messages" in enriched.text

    def test_prompt_construction_with_content_blocks(self):
        """Content blocks (list format) are correctly extracted."""
        from cc_dump.data_dispatcher import _build_summary_prompt
        from cc_dump.prompt_registry import get_prompt_spec

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is Python?"},
                    {"type": "image", "source": "..."},
                ],
            }
        ]
        prompt = _build_summary_prompt(messages, get_prompt_spec("block_summary"))

        assert "What is Python?" in prompt
        assert "[user]" in prompt

    def test_prompt_truncates_long_messages(self):
        """Individual messages are truncated to 500 chars."""
        from cc_dump.data_dispatcher import _build_summary_prompt
        from cc_dump.prompt_registry import get_prompt_spec

        messages = [{"role": "assistant", "content": "x" * 1000}]
        prompt = _build_summary_prompt(messages, get_prompt_spec("block_summary"))

        # Should be truncated to 500 + "..."
        assert "..." in prompt
        # The full 1000 chars should NOT be present
        assert "x" * 1000 not in prompt
