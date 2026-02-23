"""Tests for side-channel manager and data dispatcher."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

from cc_dump.ai.side_channel import SideChannelManager, SideChannelResult
from cc_dump.ai.data_dispatcher import DataDispatcher
from cc_dump.ai.conversation_qa import QAScope, SCOPE_WHOLE_SESSION


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

    @dataclass
    class _CacheEntry:
        summary_text: str

    class _MemorySummaryCache:
        def __init__(self):
            self._entries = {}

        def make_key(self, *, purpose: str, prompt_version: str, content: str) -> str:
            return f"{purpose}:{prompt_version}:{content}"

        def get(self, key: str):
            return self._entries.get(key)

        def put(self, *, key: str, purpose: str, prompt_version: str, content: str, summary_text: str):
            self._entries[key] = TestDataDispatcher._CacheEntry(summary_text=summary_text)

    def _make_dispatcher(self, enabled=True, query_result=None, summary_cache=None):
        """Helper to create a dispatcher with a mock side-channel."""
        mgr = SideChannelManager()
        mgr.enabled = enabled
        if query_result is not None:
            mgr.run = MagicMock(return_value=query_result)
        cache = summary_cache if summary_cache is not None else self._MemorySummaryCache()
        return DataDispatcher(mgr, summary_cache=cache), mgr, cache

    def test_summarize_when_enabled(self):
        """Enabled dispatcher routes to AI."""
        result = SideChannelResult(text="AI summary here", error=None, elapsed_ms=500)
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True, query_result=result)

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
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=False)
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
        dispatcher, _, _cache = self._make_dispatcher(enabled=True, query_result=result)

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
        dispatcher, _, _cache = self._make_dispatcher(enabled=True, query_result=result)
        messages = [{"role": "user", "content": "hello"}]
        enriched = dispatcher.summarize_messages(messages)
        assert enriched.source == "fallback"
        assert "side-channel blocked" in enriched.text
        assert "1 messages" in enriched.text

    def test_fallback_summary_empty(self):
        """Empty message list produces appropriate fallback."""
        dispatcher, _, _cache = self._make_dispatcher(enabled=False)

        enriched = dispatcher.summarize_messages([])

        assert enriched.source == "fallback"
        assert "No messages" in enriched.text

    def test_prompt_construction_with_content_blocks(self):
        """Content blocks (list format) are correctly extracted."""
        from cc_dump.ai.data_dispatcher import _build_summary_context, _build_summary_prompt
        from cc_dump.ai.prompt_registry import get_prompt_spec

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is Python?"},
                    {"type": "image", "source": "..."},
                ],
            }
        ]
        context = _build_summary_context(messages)
        prompt = _build_summary_prompt(context, get_prompt_spec("block_summary"))

        assert "What is Python?" in prompt
        assert "[user]" in prompt

    def test_prompt_truncates_long_messages(self):
        """Individual messages are truncated to 500 chars."""
        from cc_dump.ai.data_dispatcher import _build_summary_context, _build_summary_prompt
        from cc_dump.ai.prompt_registry import get_prompt_spec

        messages = [{"role": "assistant", "content": "x" * 1000}]
        context = _build_summary_context(messages)
        prompt = _build_summary_prompt(context, get_prompt_spec("block_summary"))

        # Should be truncated to 500 + "..."
        assert "..." in prompt
        # The full 1000 chars should NOT be present
        assert "x" * 1000 not in prompt

    def test_repeated_summary_request_hits_cache(self):
        result = SideChannelResult(text="AI summary here", error=None, elapsed_ms=500)
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True, query_result=result)
        messages = [{"role": "user", "content": "hello"}]

        first = dispatcher.summarize_messages(messages)
        second = dispatcher.summarize_messages(messages)

        assert first.source == "ai"
        assert second.source == "cache"
        assert second.text == "AI summary here"
        mgr.run.assert_called_once()

    def test_extract_decision_ledger_from_ai_json(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text=(
                    '{"decisions":[{"decision_id":"dec_x","statement":"Use queue-based routing",'
                    '"status":"accepted","source_links":[{"message_index":1}]}]}'
                ),
                error=None,
                elapsed_ms=12,
            )
        )
        result = dispatcher.extract_decision_ledger(
            [{"role": "user", "content": "decide routing"}],
            source_session_id="sess-1",
            request_id="req-1",
        )
        assert result.source == "ai"
        assert len(result.entries) == 1
        assert result.entries[0].decision_id == "dec_x"
        assert result.entries[0].status == "accepted"
        assert result.entries[0].source_links[0].message_index == 1
        assert result.entries[0].source_links[0].request_id == "req-1"

    def test_extract_decision_ledger_guardrail_falls_back(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text="",
                error="Guardrail: purpose disabled (decision_ledger)",
                elapsed_ms=0,
            )
        )
        result = dispatcher.extract_decision_ledger(
            [{"role": "user", "content": "decide routing"}],
            source_session_id="sess-1",
            request_id="req-1",
        )
        assert result.source == "fallback"
        assert result.entries == []

    def test_create_checkpoint_with_selected_range_uses_checkpoint_purpose(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text="Checkpoint summary text",
                error=None,
                elapsed_ms=21,
            )
        )
        messages = [
            {"role": "user", "content": "m0"},
            {"role": "assistant", "content": "m1"},
            {"role": "user", "content": "m2"},
        ]
        result = dispatcher.create_checkpoint(
            messages,
            source_start=1,
            source_end=2,
            source_session_id="sess-a",
            request_id="req-a",
        )
        assert result.source == "ai"
        assert result.artifact.source_start == 1
        assert result.artifact.source_end == 2
        assert result.artifact.source_session_id == "sess-a"
        assert result.artifact.request_id == "req-a"
        assert result.artifact.summary_text == "Checkpoint summary text"
        run_call = mgr.run.call_args
        assert run_call.kwargs["purpose"] == "checkpoint_summary"
        assert run_call.kwargs["prompt_version"] == "v1"
        assert run_call.kwargs["profile"] == "cache_probe_resume"

    def test_create_checkpoint_disabled_uses_fallback_and_skips_ai(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=False)
        mgr.run = MagicMock()
        result = dispatcher.create_checkpoint(
            [{"role": "user", "content": "m0"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-a",
            request_id="req-a",
        )
        assert result.source == "fallback"
        assert "1 messages" in result.artifact.summary_text
        mgr.run.assert_not_called()

    def test_create_checkpoint_guardrail_falls_back(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text="",
                error="Guardrail: purpose disabled (checkpoint_summary)",
                elapsed_ms=0,
            )
        )
        result = dispatcher.create_checkpoint(
            [{"role": "user", "content": "m0"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-a",
            request_id="req-a",
        )
        assert result.source == "fallback"
        assert "1 messages" in result.artifact.summary_text

    def test_checkpoint_diff_links_ids_and_ranges(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=False)
        mgr.run = MagicMock()

        before = dispatcher.create_checkpoint(
            [{"role": "user", "content": "m0"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-a",
            request_id="req-before",
        )
        after = dispatcher.create_checkpoint(
            [{"role": "assistant", "content": "m0"}, {"role": "assistant", "content": "m1"}],
            source_start=0,
            source_end=1,
            source_session_id="sess-a",
            request_id="req-after",
        )
        diff_text = dispatcher.checkpoint_diff(
            before_checkpoint_id=before.artifact.checkpoint_id,
            after_checkpoint_id=after.artifact.checkpoint_id,
        )
        assert before.artifact.checkpoint_id in diff_text
        assert after.artifact.checkpoint_id in diff_text
        assert "source_ranges:0-0|0-1" in diff_text

    def test_extract_action_items_stages_pending_without_auto_persist(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text=(
                    '{"items":[{"kind":"action","text":"Write tests for extraction",'
                    '"confidence":0.8,"source_links":[{"message_index":1}]}]}'
                ),
                error=None,
                elapsed_ms=12,
            )
        )
        result = dispatcher.extract_action_items(
            [{"role": "user", "content": "next steps"}],
            source_session_id="sess-1",
            request_id="req-1",
        )
        assert result.source == "ai"
        assert len(result.items) == 1
        assert dispatcher.accepted_action_items_snapshot() == []
        pending = dispatcher.pending_action_items(result.batch_id)
        assert len(pending) == 1
        assert pending[0].text == "Write tests for extraction"

    def test_accept_action_items_persists_selected_items(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text=(
                    '{"items":[{"kind":"action","text":"Ship am0",'
                    '"confidence":0.9,"source_links":[{"message_index":1}]}]}'
                ),
                error=None,
                elapsed_ms=12,
            )
        )
        extraction = dispatcher.extract_action_items(
            [{"role": "user", "content": "next steps"}],
            source_session_id="sess-1",
            request_id="req-1",
        )
        item_id = extraction.items[0].item_id
        accepted = dispatcher.accept_action_items(
            batch_id=extraction.batch_id,
            item_ids=[item_id],
            create_beads=True,
            beads_hook=lambda _item: "cc-dump-901",
        )
        assert len(accepted) == 1
        assert accepted[0].status == "accepted"
        assert accepted[0].beads_issue_id == "cc-dump-901"
        snapshot = dispatcher.accepted_action_items_snapshot()
        assert len(snapshot) == 1
        assert snapshot[0].item_id == item_id

    def test_accept_action_items_ignores_beads_hook_without_confirmation(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text='{"items":[{"kind":"action","text":"Draft notes","source_links":[{"message_index":0}]}]}',
                error=None,
                elapsed_ms=12,
            )
        )
        extraction = dispatcher.extract_action_items(
            [{"role": "user", "content": "next steps"}],
            source_session_id="sess-1",
            request_id="req-1",
        )
        item_id = extraction.items[0].item_id
        accepted = dispatcher.accept_action_items(
            batch_id=extraction.batch_id,
            item_ids=[item_id],
            create_beads=False,
            beads_hook=lambda _item: "cc-dump-should-not-appear",
        )
        assert len(accepted) == 1
        assert accepted[0].beads_issue_id == ""

    def test_generate_handoff_note_returns_required_sections(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text=(
                    '{"sections":{"changed":[{"text":"Implemented lane routing",'
                    '"source_links":[{"message_index":1}]}],'
                    '"decisions":[{"text":"Use side-channel marker","source_links":[{"message_index":2}]}],'
                    '"open_work":[],"risks":[],"next_steps":[{"text":"Wire UI","source_links":[{"message_index":3}]}]}}'
                ),
                error=None,
                elapsed_ms=17,
            )
        )
        result = dispatcher.generate_handoff_note(
            [{"role": "user", "content": "handoff context"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-1",
            request_id="req-1",
        )
        assert result.source == "ai"
        assert "## changed" in result.markdown
        assert "## decisions" in result.markdown
        assert "## open work" in result.markdown
        assert "## risks" in result.markdown
        assert "## next steps" in result.markdown

    def test_generate_handoff_note_fallback_when_disabled(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=False)
        mgr.run = MagicMock()
        result = dispatcher.generate_handoff_note(
            [{"role": "assistant", "content": "worked on cache"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-1",
            request_id="req-1",
        )
        assert result.source == "fallback"
        assert "## changed" in result.markdown
        assert "## next steps" in result.markdown
        mgr.run.assert_not_called()

    def test_latest_handoff_note_available_for_resume_flow(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text='{"sections":{"changed":[{"text":"A","source_links":[{"message_index":0}]}]}}',
                error=None,
                elapsed_ms=11,
            )
        )
        result = dispatcher.generate_handoff_note(
            [{"role": "assistant", "content": "A"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-2",
            request_id="req-2",
        )
        latest = dispatcher.latest_handoff_note("sess-2")
        assert latest is not None
        assert latest.handoff_id == result.artifact.handoff_id

    def test_generate_incident_timeline_facts_only(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text=(
                    '{"facts":[{"timestamp":"2026-02-22T10:00:00Z","actor":"svc","action":"recover","outcome":"ok","source_links":[{"message_index":2}]},'
                    '{"timestamp":"2026-02-22T09:00:00Z","actor":"svc","action":"error","outcome":"failed","source_links":[{"message_index":1}]}],'
                    '"hypotheses":[{"timestamp":"2026-02-22T09:05:00Z","actor":"ops","action":"suspect cache","outcome":"unknown","source_links":[{"message_index":3}]}]}'
                ),
                error=None,
                elapsed_ms=13,
            )
        )
        result = dispatcher.generate_incident_timeline(
            [{"role": "assistant", "content": "incident"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-1",
            request_id="req-1",
            include_hypotheses=False,
        )
        assert result.source == "ai"
        assert "## facts" in result.markdown
        assert "## hypotheses" not in result.markdown
        assert result.artifact.hypotheses == []
        assert result.artifact.facts[0].timestamp == "2026-02-22T09:00:00Z"

    def test_generate_incident_timeline_with_hypotheses(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text=(
                    '{"facts":[{"timestamp":"2026-02-22T09:00:00Z","actor":"svc","action":"error","outcome":"failed"}],'
                    '"hypotheses":[{"timestamp":"2026-02-22T09:05:00Z","actor":"ops","action":"suspect cache","outcome":"unknown"}]}'
                ),
                error=None,
                elapsed_ms=13,
            )
        )
        result = dispatcher.generate_incident_timeline(
            [{"role": "assistant", "content": "incident"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-1",
            request_id="req-1",
            include_hypotheses=True,
        )
        assert result.source == "ai"
        assert "## hypotheses" in result.markdown
        assert len(result.artifact.hypotheses) == 1

    def test_generate_incident_timeline_fallback_when_disabled(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=False)
        mgr.run = MagicMock()
        result = dispatcher.generate_incident_timeline(
            [{"role": "assistant", "content": "incident"}],
            source_start=0,
            source_end=0,
            source_session_id="sess-1",
            request_id="req-1",
            include_hypotheses=False,
        )
        assert result.source == "fallback"
        assert "## facts" in result.markdown
        mgr.run.assert_not_called()

    def test_ask_conversation_question_returns_sources_and_estimate(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text=(
                    '{"answer":"Use decision ledger extraction first.",'
                    '"source_links":[{"message_index":1,"quote":"extract_decision_ledger(...)"}]}'
                ),
                error=None,
                elapsed_ms=14,
            )
        )
        result = dispatcher.ask_conversation_question(
            [{"role": "assistant", "content": "extract_decision_ledger(...) handles this"}],
            question="How should I track decisions?",
            request_id="req-qa-1",
        )
        assert result.source == "ai"
        assert "answer: Use decision ledger extraction first." in result.markdown
        assert "req-qa-1:1" in result.markdown
        assert result.estimate.estimated_total_tokens > 0

    def test_ask_conversation_question_whole_session_requires_explicit_selection(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock()
        result = dispatcher.ask_conversation_question(
            [{"role": "assistant", "content": "a"}, {"role": "assistant", "content": "b"}],
            question="What happened?",
            scope=QAScope(mode=SCOPE_WHOLE_SESSION, explicit_whole_session=False),
            request_id="req-qa-2",
        )
        assert result.source == "fallback"
        assert "Scope error" in result.markdown
        mgr.run.assert_not_called()

    def test_ask_conversation_question_fallback_on_guardrail(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text="",
                error="Guardrail: budget cap reached for conversation_qa: used=120 cap=100",
                elapsed_ms=0,
            )
        )
        result = dispatcher.ask_conversation_question(
            [{"role": "assistant", "content": "a"}],
            question="What happened?",
            request_id="req-qa-3",
        )
        assert result.source == "fallback"
        assert "Fallback answer based on selected scope" in result.markdown

    def test_generate_release_notes_scoped_with_variant(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text=(
                    '{"sections":{"user_highlights":[{"title":"Shipped side-channel lane","detail":"Added isolated debug lane","source_links":[{"message_index":1}]}],'
                    '"technical_changes":[{"title":"Dispatcher","detail":"Added release-note generation","source_links":[{"message_index":2}]}],'
                    '"known_issues":[],"upgrade_notes":[]}}'
                ),
                error=None,
                elapsed_ms=18,
            )
        )
        result = dispatcher.generate_release_notes(
            [{"role": "assistant", "content": "release context"}],
            source_start=0,
            source_end=0,
            variant="technical",
            source_session_id="sess-1",
            request_id="req-rel-1",
        )
        assert result.source == "ai"
        assert "## technical changes" in result.markdown
        assert "## user highlights" not in result.markdown

    def test_generate_release_notes_fallback_when_disabled(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=False)
        mgr.run = MagicMock()
        result = dispatcher.generate_release_notes(
            [{"role": "assistant", "content": "release context"}],
            source_start=0,
            source_end=0,
            request_id="req-rel-2",
        )
        assert result.source == "fallback"
        assert "## user highlights" in result.markdown
        mgr.run.assert_not_called()

    def test_render_release_notes_draft_for_review_export(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=False)
        mgr.run = MagicMock()
        generated = dispatcher.generate_release_notes(
            [{"role": "assistant", "content": "release context"}],
            source_start=0,
            source_end=0,
            request_id="req-rel-3",
        )
        rendered = dispatcher.render_release_notes_draft(
            artifact_id=generated.artifact.artifact_id,
            variant="technical",
        )
        assert "## technical changes" in rendered

    def test_list_utilities_returns_registered_catalog(self):
        dispatcher, _mgr, _cache = self._make_dispatcher(enabled=False)
        utilities = dispatcher.list_utilities()
        assert len(utilities) >= 3
        assert any(spec.utility_id == "turn_title" for spec in utilities)

    def test_run_utility_uses_ai_when_enabled(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=True)
        mgr.run = MagicMock(
            return_value=SideChannelResult(
                text="Debug lane rollout",
                error=None,
                elapsed_ms=11,
                purpose="utility_custom",
            )
        )
        result = dispatcher.run_utility(
            [{"role": "assistant", "content": "implemented debug lane"}],
            utility_id="turn_title",
            source_session_id="sess-1",
        )
        assert result.source == "ai"
        assert result.text == "Debug lane rollout"

    def test_run_utility_falls_back_when_disabled(self):
        dispatcher, mgr, _cache = self._make_dispatcher(enabled=False)
        mgr.run = MagicMock()
        result = dispatcher.run_utility(
            [{"role": "assistant", "content": "implemented debug lane"}],
            utility_id="turn_title",
        )
        assert result.source == "fallback"
        assert result.text
        mgr.run.assert_not_called()

    def test_run_utility_unknown_id_returns_error(self):
        dispatcher, _mgr, _cache = self._make_dispatcher(enabled=False)
        result = dispatcher.run_utility(
            [{"role": "assistant", "content": "implemented debug lane"}],
            utility_id="not_real",
        )
        assert result.source == "error"
        assert "Unknown utility" in result.text
