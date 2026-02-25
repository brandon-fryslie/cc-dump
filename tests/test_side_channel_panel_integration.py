"""Integration-level smoke tests for Side Channel panel entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cc_dump.ai.action_items import ActionWorkItem, parse_action_items
from cc_dump.ai.data_dispatcher import ActionExtractionResult
from cc_dump.tui.chip import Chip
from cc_dump.tui.side_channel_panel import (
    PromptEditorDraft,
    SideChannelPanel,
    SideChannelPanelState,
)
from textual.widgets import Checkbox, Input
from tests.harness import run_app


pytestmark = pytest.mark.textual


@dataclass
class _StubDispatcher:
    batch_id: str = "batch-int-1"

    def __post_init__(self) -> None:
        payload = (
            '{"items":['
            '{"kind":"action","text":"Ship lane routing","confidence":0.9,"source_links":[{"message_index":1}]},'
            '{"kind":"deferred","text":"Revisit compaction policy","confidence":0.5,"source_links":[{"message_index":2}]}'
            ']}'
        )
        self._items = parse_action_items(payload, request_id="req-int")
        self.accept_calls: list[dict] = []

    def extract_action_items(self, *_args, **_kwargs) -> ActionExtractionResult:
        return ActionExtractionResult(
            batch_id=self.batch_id,
            items=list(self._items),
            source="ai",
            elapsed_ms=3,
            error="",
        )

    def prepare_action_extraction_prompt(self, _messages):
        class _Prepared:
            prompt = "Extract action items from provided context."

        return _Prepared()

    def accept_action_items(self, *, batch_id: str, item_ids: list[str], create_beads: bool = False):
        self.accept_calls.append(
            {
                "batch_id": batch_id,
                "item_ids": list(item_ids),
                "create_beads": bool(create_beads),
            }
        )
        accepted: list[ActionWorkItem] = []
        for item in self._items:
            if item.item_id in item_ids:
                accepted.append(
                    ActionWorkItem(
                        item_id=item.item_id,
                        kind=item.kind,
                        text=item.text,
                        confidence=item.confidence,
                        owner=item.owner,
                        due_hint=item.due_hint,
                        source_links=item.source_links,
                        status="accepted",
                        beads_issue_id="",
                        created_at=item.created_at,
                    )
                )
        return accepted


async def test_side_channel_panel_exposes_integrated_entrypoint_controls():
    async with run_app() as (pilot, app):
        app.action_toggle_side_channel()
        await pilot.pause()
        panel = app.screen.query(SideChannelPanel).first()
        panel.update_display(
            SideChannelPanelState(
                enabled=True,
                loading=False,
                active_action="",
                result_text="",
                result_source="",
                result_elapsed_ms=0,
                purpose_usage={},
            )
        )
        expected = {
            "sc-summarize_recent": "app.sc_summarize_recent",
            "sc-qa_estimate": "app.sc_qa_estimate",
            "sc-qa_submit": "app.sc_qa_submit",
            "sc-action_extract": "app.sc_action_extract",
            "sc-action_apply_review": "app.sc_action_apply_review",
            "sc-prompt_preview": "app.sc_prompt_preview",
        }
        for widget_id, action in expected.items():
            chip = panel.query_one(f"#{widget_id}", Chip)
            assert chip._action == action


async def test_side_channel_panel_action_review_flow_smoke():
    async with run_app() as (pilot, app):
        app._data_dispatcher = _StubDispatcher()
        app._app_state["recent_messages"] = [
            {"role": "user", "content": "extract next actions"},
            {"role": "assistant", "content": "implemented lane routing and deferred compaction policy"},
        ]
        app.action_toggle_side_channel()
        await pilot.pause()

        app.action_sc_action_extract()
        await pilot.pause()
        assert "action extraction review" in app._view_store.get("sc:result_text")
        assert "candidate_count: 2" in app._view_store.get("sc:result_text")

        panel = app.screen.query(SideChannelPanel).first()
        panel.query_one("#sc-action-accept", Input).value = "0"
        panel.query_one("#sc-action-reject", Input).value = "1"
        panel.query_one("#sc-action-beads", Checkbox).value = True

        app.action_sc_action_apply_review()
        await pilot.pause()
        assert "action review applied" in app._view_store.get("sc:result_text")
        assert "accepted_count: 1" in app._view_store.get("sc:result_text")
        assert "rejected_count: 1" in app._view_store.get("sc:result_text")
        assert app._data_dispatcher.accept_calls
        assert app._data_dispatcher.accept_calls[0]["create_beads"] is True


async def test_side_channel_prompt_preview_populates_editor_and_results():
    class _StubPreviewDispatcher:
        def prepare_summary_prompt(self, _messages):
            class _Prepared:
                prompt = "Prompt body"
                purpose = "block_summary"
                prompt_version = "v1"

            return _Prepared()

    async with run_app() as (pilot, app):
        app._app_state["recent_messages"] = [
            {"role": "user", "content": "please summarize this planning session"},
            {"role": "assistant", "content": "we implemented prompt preview and override wiring"},
        ]
        app._data_dispatcher = _StubPreviewDispatcher()
        app.action_toggle_side_channel()
        await pilot.pause()

        app.action_sc_prompt_preview()
        await pilot.pause()

        assert "prompt preview" in app._view_store.get("sc:result_text")
        assert "purpose:" in app._view_store.get("sc:result_text")


async def test_side_channel_prompt_override_is_forwarded_to_dispatcher():
    @dataclass
    class _SummaryResult:
        text: str
        source: str
        elapsed_ms: int

    class _StubSummaryDispatcher:
        def __init__(self) -> None:
            self.last_prompt_override = None

        def prepare_summary_prompt(self, _messages):
            class _Prepared:
                prompt = "DEFAULT_PROMPT"

            return _Prepared()

        def summarize_messages(self, _messages, *, source_session_id="", prompt_override=None):
            self.last_prompt_override = prompt_override
            return _SummaryResult(text="ok", source="ai", elapsed_ms=1)

    async with run_app() as (pilot, app):
        app._app_state["recent_messages"] = [
            {"role": "user", "content": "summarize this"},
        ]
        app.action_toggle_side_channel()
        await pilot.pause()
        panel = app.screen.query(SideChannelPanel).first()
        panel.read_prompt_editor_draft = lambda: PromptEditorDraft(
            target_action="summarize_recent",
            use_override=True,
            prompt_text="OVERRIDE_PROMPT",
        )
        stub = _StubSummaryDispatcher()
        app._data_dispatcher = stub

        app.action_sc_summarize_recent()
        await pilot.pause()

        assert stub.last_prompt_override == "OVERRIDE_PROMPT"
