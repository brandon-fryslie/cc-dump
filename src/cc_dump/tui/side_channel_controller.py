"""Side-channel control plane extracted from CcDumpApp.

// [LAW:locality-or-seam] Side-channel workflows live behind this module seam.
// [LAW:one-source-of-truth] View-store keys remain canonical; this module only projects updates.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import cast

import cc_dump.ai.conversation_qa
import cc_dump.providers
import cc_dump.tui.side_channel_panel
from snarfx import transaction


@dataclass(frozen=True)
class PreparedQARequest:
    question: str
    scope: cc_dump.ai.conversation_qa.QAScope
    normalized_scope: cc_dump.ai.conversation_qa.NormalizedQAScope
    selected_messages: list[dict]
    estimate: cc_dump.ai.conversation_qa.QABudgetEstimate
    error: str


def _ensure_side_channel_panel(app):
    panel = get_side_channel_panel_widget(app)
    if panel is None:
        panel = cc_dump.tui.side_channel_panel.create_side_channel_panel()
        panel.display = False
        app.screen.mount(panel)
    return panel


def _side_channel_usage_summary(app) -> dict:
    return (
        app._analytics_store.get_side_channel_purpose_summary()
        if app._analytics_store is not None
        else {}
    )

def open_side_channel(app) -> None:
    """Open AI Workbench sidebar and hydrate panel state."""
    _ensure_side_channel_panel(app)
    context_key = app._context_session_key(app._active_context_session_key())
    # [LAW:dataflow-not-control-flow] Single snapshot update avoids intermediate UI states.
    app._view_store.update(
        {
            "panel:settings": False,
            "panel:launch_config": False,
            "panel:side_channel": True,
            "sc:loading": False,
            "sc:active_action": "",
            "sc:result_text": "",
            "sc:result_source": "",
            "sc:result_elapsed_ms": 0,
            "sc:purpose_usage": _side_channel_usage_summary(app),
            "workbench:text": "",
            "workbench:source": "",
            "workbench:elapsed_ms": 0,
            "workbench:action": "",
            "workbench:context_session_id": context_key,
        }
    )


def close_side_channel(app) -> None:
    """Hide AI Workbench sidebar."""
    app._view_store.set("panel:side_channel", False)


def refresh_side_channel_usage(app) -> None:
    """Project side-channel usage totals from AnalyticsStore into view store.

    // [LAW:one-source-of-truth] AnalyticsStore is canonical source for usage aggregates.
    """
    app._view_store.set("sc:purpose_usage", _side_channel_usage_summary(app))


def collect_recent_messages(app, count: int) -> list[dict]:
    recent_messages = cast(list[dict], app._app_state.get("recent_messages", []))
    return recent_messages[-count:]


def get_side_channel_panel_widget(app):
    panel = app.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel)
    return panel.first() if panel else None


def _parse_indices_scope(mode: str, indices_text: str) -> tuple[cc_dump.ai.conversation_qa.QAScope, str]:
    stripped = indices_text.strip()
    if not stripped:
        return (cc_dump.ai.conversation_qa.QAScope(mode=mode, indices=()), "")
    parts = [part.strip() for part in stripped.split(",") if part.strip()]
    try:
        indices = tuple(sorted({int(part) for part in parts}))
    except ValueError:
        return (
            cc_dump.ai.conversation_qa.QAScope(mode=mode, indices=()),
            "indices must be integers",
        )
    return (cc_dump.ai.conversation_qa.QAScope(mode=mode, indices=indices), "")


def _default_scope_range(total_messages: int) -> tuple[int, int]:
    return (max(0, total_messages - 10), max(0, total_messages - 1))


def _parse_range_scope(
    draft,
    *,
    total_messages: int,
) -> tuple[cc_dump.ai.conversation_qa.QAScope, str]:
    default_start, default_end = _default_scope_range(total_messages)
    start_text = draft.source_start_text.strip()
    end_text = draft.source_end_text.strip()
    try:
        start = int(start_text) if start_text else default_start
        end = int(end_text) if end_text else default_end
    except ValueError:
        return (
            cc_dump.ai.conversation_qa.QAScope(
                mode=cc_dump.ai.conversation_qa.SCOPE_SELECTED_RANGE
            ),
            "range start/end must be integers",
        )
    return (
        cc_dump.ai.conversation_qa.QAScope(
            mode=cc_dump.ai.conversation_qa.SCOPE_SELECTED_RANGE,
            source_start=start,
            source_end=end,
        ),
        "",
    )


def parse_qa_scope(draft, *, total_messages: int) -> tuple[cc_dump.ai.conversation_qa.QAScope, str]:
    """Build and validate QAScope from panel draft controls.

    // [LAW:single-enforcer] Scope parsing and normalization entrypoint is centralized here.
    """
    mode = str(draft.scope_mode or cc_dump.ai.conversation_qa.SCOPE_SELECTED_RANGE)
    scope_parsers = {
        cc_dump.ai.conversation_qa.SCOPE_WHOLE_SESSION: lambda: (
            cc_dump.ai.conversation_qa.QAScope(
                mode=mode,
                explicit_whole_session=bool(draft.explicit_whole_session),
            ),
            "",
        ),
        cc_dump.ai.conversation_qa.SCOPE_SELECTED_INDICES: lambda: _parse_indices_scope(
            mode,
            draft.indices_text,
        ),
    }
    # [LAW:dataflow-not-control-flow] Operation order is fixed; mode selects values/parser only.
    return scope_parsers.get(mode, lambda: _parse_range_scope(draft, total_messages=total_messages))()


def prepare_qa_request(
    draft,
    *,
    messages: list[dict],
    require_messages: bool,
) -> PreparedQARequest:
    """Build reusable scoped-QA payload from panel draft data.

    // [LAW:single-enforcer] Scope parsing, normalization, selection, estimate, and validation are centralized.
    """
    scope, parse_error = parse_qa_scope(draft, total_messages=len(messages))
    normalized_scope = cc_dump.ai.conversation_qa.normalize_scope(
        scope,
        total_messages=len(messages),
    )
    selected_messages = cc_dump.ai.conversation_qa.select_messages(
        messages,
        normalized_scope,
    )
    estimate = cc_dump.ai.conversation_qa.estimate_qa_budget(
        question=draft.question,
        selected_messages=selected_messages,
        scope_mode=normalized_scope.scope.mode,
    )

    question = draft.question.strip()
    error = parse_error or normalized_scope.error
    if not question:
        error = "question is required"
    if require_messages and not messages:
        error = "no captured messages available"
    return PreparedQARequest(
        question=question,
        scope=scope,
        normalized_scope=normalized_scope,
        selected_messages=selected_messages,
        estimate=estimate,
        error=error,
    )


def render_qa_result_text(
    app,
    *,
    question: str,
    scope_mode: str,
    selected_indices: tuple[int, ...],
    estimate,
    body: str,
    prefix: str,
    error: str = "",
) -> str:
    lines = [
        prefix,
        cc_dump.tui.side_channel_panel.render_qa_scope_line(
            scope_mode=scope_mode,
            selected_indices=selected_indices,
        ),
        cc_dump.tui.side_channel_panel.render_qa_estimate_line(
            scope_mode=estimate.scope_mode,
            message_count=estimate.message_count,
            estimated_input_tokens=estimate.estimated_input_tokens,
            estimated_output_tokens=estimate.estimated_output_tokens,
            estimated_total_tokens=estimate.estimated_total_tokens,
        ),
        f"question: {question}",
    ]
    if error:
        lines.append(f"error: {error}")
    if body:
        lines.extend(["", body])
    return "\n".join(lines)


def set_side_channel_result(
    app,
    *,
    text: str,
    source: str,
    elapsed_ms: int,
    loading: bool = False,
    active_action: str = "",
    focus_results: bool = False,
    context_session_key: str | None = None,
) -> None:
    context_key = app._context_session_key(
        context_session_key
        if isinstance(context_session_key, str)
        else app._active_context_session_key()
    )
    with transaction():
        app._view_store.set("sc:loading", loading)
        app._view_store.set("sc:active_action", active_action)
        app._view_store.set("sc:result_text", text)
        app._view_store.set("sc:result_source", source)
        app._view_store.set("sc:result_elapsed_ms", elapsed_ms)
        app._view_store.set("workbench:text", text)
        app._view_store.set("workbench:source", source)
        app._view_store.set("workbench:elapsed_ms", elapsed_ms)
        app._view_store.set("workbench:action", active_action)
        app._view_store.set("workbench:context_session_id", context_key)
    if focus_results:
        app._show_workbench_results_tab()


def workbench_preview(app, feature: str, owner_ticket: str) -> None:
    """Publish deterministic placeholder output for non-integrated controls."""
    preview = (
        f"{feature} is planned but not wired in this panel yet.\n"
        f"Owner: {owner_ticket}\n"
        "No side effects were executed."
    )
    set_side_channel_result(
        app,
        text=preview,
        source="preview",
        elapsed_ms=0,
        loading=False,
        active_action="",
        focus_results=True,
    )


def action_sc_qa_estimate(app) -> None:
    panel = get_side_channel_panel_widget(app)
    if panel is None:
        return
    draft = panel.read_qa_draft()
    messages = collect_recent_messages(app, 50)
    prepared = prepare_qa_request(
        draft,
        messages=messages,
        require_messages=False,
    )
    body = "Ready to ask scoped Q&A." if not prepared.error else ""
    text = render_qa_result_text(
        app,
        question=prepared.question or "(empty)",
        scope_mode=prepared.normalized_scope.scope.mode,
        selected_indices=prepared.normalized_scope.selected_indices,
        estimate=prepared.estimate,
        body=body,
        prefix="pre-send estimate",
        error=prepared.error,
    )
    set_side_channel_result(
        app,
        text=text,
        source="preview",
        elapsed_ms=0,
        loading=False,
        active_action="",
        focus_results=True,
    )


def action_sc_qa_submit(app) -> None:
    if app._view_store.get("sc:loading"):
        return
    panel = get_side_channel_panel_widget(app)
    if panel is None:
        return
    context_session_key = app._active_context_session_key()
    draft = panel.read_qa_draft()
    messages = collect_recent_messages(app, 50)
    prepared = prepare_qa_request(
        draft,
        messages=messages,
        require_messages=True,
    )
    if prepared.error:
        text = render_qa_result_text(
            app,
            question=prepared.question or "(empty)",
            scope_mode=prepared.normalized_scope.scope.mode,
            selected_indices=prepared.normalized_scope.selected_indices,
            estimate=prepared.estimate,
            body="",
            prefix="scoped Q&A blocked",
            error=prepared.error,
        )
        set_side_channel_result(
            app,
            text=text,
            source="fallback",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        return

    if app._data_dispatcher is None:
        text = render_qa_result_text(
            app,
            question=prepared.question,
            scope_mode=prepared.normalized_scope.scope.mode,
            selected_indices=prepared.normalized_scope.selected_indices,
            estimate=prepared.estimate,
            body="",
            prefix="scoped Q&A blocked",
            error="dispatcher unavailable",
        )
        set_side_channel_result(
            app,
            text=text,
            source="fallback",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        return

    set_side_channel_result(
        app,
        text="Running scoped Q&A…",
        source="preview",
        elapsed_ms=0,
        loading=True,
        active_action="qa_submit",
        context_session_key=context_session_key,
    )

    dispatcher = app._data_dispatcher
    source_provider = cc_dump.providers.session_provider(
        app._active_session_key_from_tabs(),
        default_session_key=app._default_session_key,
    )
    request_id = f"sc-qa-{int(time.time() * 1000)}"

    def _do_qa() -> None:
        result = dispatcher.ask_conversation_question(
            messages,
            question=prepared.question,
            scope=prepared.scope,
            source_provider=source_provider,
            request_id=request_id,
        )
        app.call_from_thread(
            app._on_side_channel_qa_result,
            result,
            prepared.question,
            context_session_key,
        )

    app.run_worker(_do_qa, thread=True, exclusive=False)


def on_side_channel_qa_result(app, result, question: str, context_session_key: str) -> None:
    text = render_qa_result_text(
        app,
        question=question,
        scope_mode=result.artifact.scope_mode,
        selected_indices=tuple(result.artifact.selected_indices),
        estimate=result.estimate,
        body=result.markdown,
        prefix="scoped Q&A result",
        error=result.error,
    )
    set_side_channel_result(
        app,
        text=text,
        source=result.source,
        elapsed_ms=result.elapsed_ms,
        loading=False,
        active_action="",
        focus_results=True,
        context_session_key=context_session_key,
    )
    refresh_side_channel_usage(app)


def action_sc_utility_run(app) -> None:
    if app._view_store.get("sc:loading"):
        return
    panel = get_side_channel_panel_widget(app)
    if panel is None:
        return
    context_session_key = app._active_context_session_key()
    draft = panel.read_utility_draft()
    utility_id = draft.utility_id.strip()
    if not utility_id:
        set_side_channel_result(
            app,
            text="utility run blocked\nerror: no utility selected",
            source="fallback",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        return
    if app._data_dispatcher is None:
        set_side_channel_result(
            app,
            text=f"utility run blocked\nutility_id: {utility_id}\nerror: dispatcher unavailable",
            source="fallback",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        return

    messages = collect_recent_messages(app, 50)
    set_side_channel_result(
        app,
        text=f"Running utility {utility_id}…",
        source="preview",
        elapsed_ms=0,
        loading=True,
        active_action="utility_run",
        context_session_key=context_session_key,
    )

    dispatcher = app._data_dispatcher
    source_provider = cc_dump.providers.session_provider(
        app._active_session_key_from_tabs(),
        default_session_key=app._default_session_key,
    )

    def _do_utility_run() -> None:
        result = dispatcher.run_utility(
            messages,
            utility_id=utility_id,
            source_provider=source_provider,
        )
        app.call_from_thread(
            app._on_side_channel_utility_result,
            result,
            context_session_key,
        )

    app.run_worker(_do_utility_run, thread=True, exclusive=False)


def on_side_channel_utility_result(app, result, context_session_key: str) -> None:
    lines = [
        "utility result",
        f"utility_id: {result.utility_id}",
        f"source: {result.source}",
    ]
    if result.error:
        lines.append(f"error: {result.error}")
    lines.extend(["", result.text])
    set_side_channel_result(
        app,
        text="\n".join(lines),
        source=result.source,
        elapsed_ms=result.elapsed_ms,
        loading=False,
        active_action="",
        focus_results=True,
        context_session_key=context_session_key,
    )
    refresh_side_channel_usage(app)


def action_sc_preview_qa(app) -> None:
    action_sc_qa_submit(app)


def action_sc_preview_handoff(app) -> None:
    workbench_preview(app, "Handoff Draft", "cc-dump-mjb.4")


def action_sc_preview_utilities(app) -> None:
    action_sc_utility_run(app)
