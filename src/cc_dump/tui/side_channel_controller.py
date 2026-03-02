"""Side-channel control plane extracted from CcDumpApp.

// [LAW:locality-or-seam] Side-channel workflows live behind this module seam.
// [LAW:one-source-of-truth] View-store keys remain canonical; this module only projects updates.
"""

from __future__ import annotations

import time
from typing import cast

import cc_dump.ai.conversation_qa
import cc_dump.providers
import cc_dump.tui.side_channel_panel
from snarfx import transaction


def open_side_channel(app) -> None:
    """Open AI Workbench sidebar and hydrate panel state."""
    app._view_store.set("panel:side_channel", True)
    panel = cc_dump.tui.side_channel_panel.create_side_channel_panel()
    app.screen.mount(panel)
    set_side_channel_result(
        app,
        text="",
        source="",
        elapsed_ms=0,
        loading=False,
        active_action="",
    )
    app._view_store.set("sc:purpose_usage", {})
    app._sc_action_batch_id = ""
    app._sc_action_items = []
    refresh_side_channel_usage(app)
    app.call_after_refresh(
        lambda: panel.update_display(
            cc_dump.tui.side_channel_panel.SideChannelPanelState(
                **app._view_store.sc_panel_state.get()
            )
        )
    )


def close_side_channel(app) -> None:
    """Close AI Workbench sidebar and restore conversation focus."""
    for panel in app.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel):
        panel.remove()
    app._view_store.set("panel:side_channel", False)
    conv = app._get_conv()
    if conv is not None:
        conv.focus()


def side_channel_summarize(app) -> None:
    """Request AI summary of recent messages via worker thread."""
    if app._view_store.get("sc:loading") or app._data_dispatcher is None:
        return

    context_session_key = app._active_context_session_key()
    messages = collect_recent_messages(app, 10)
    if not messages:
        set_side_channel_result(
            app,
            text="No messages to summarize.",
            source="fallback",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        return

    with transaction():
        app._view_store.set("sc:loading", True)
        app._view_store.set("sc:active_action", "summarize_recent")

    dispatcher = app._data_dispatcher
    source_provider = cc_dump.providers.session_provider(
        app._active_session_key_from_tabs(),
        default_session_key=app._default_session_key,
    )

    def _do_summarize() -> None:
        result = dispatcher.summarize_messages(messages, source_provider=source_provider)
        app.call_from_thread(app._on_side_channel_result, result, context_session_key)

    app.run_worker(_do_summarize, thread=True, exclusive=False)


def on_side_channel_result(app, result, context_session_key: str) -> None:
    """Callback from summarize worker thread with result payload."""
    set_side_channel_result(
        app,
        text=result.text,
        source=result.source,
        elapsed_ms=result.elapsed_ms,
        loading=False,
        active_action="",
        focus_results=True,
        context_session_key=context_session_key,
    )
    refresh_side_channel_usage(app)


def refresh_side_channel_usage(app) -> None:
    """Project side-channel usage totals from AnalyticsStore into view store.

    // [LAW:one-source-of-truth] AnalyticsStore is canonical source for usage aggregates.
    """
    usage = (
        app._analytics_store.get_side_channel_purpose_summary()
        if app._analytics_store is not None
        else {}
    )
    app._view_store.set("sc:purpose_usage", usage)


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
    workbench_results = app._get_workbench_results_view()
    if workbench_results is not None:
        workbench_results.update_result(
            text=text,
            source=source,
            elapsed_ms=elapsed_ms,
            action=active_action,
            context_session_id=context_key,
        )
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


def action_sc_summarize_recent(app) -> None:
    side_channel_summarize(app)


def action_sc_summarize(app) -> None:
    action_sc_summarize_recent(app)


def action_sc_qa_estimate(app) -> None:
    panel = get_side_channel_panel_widget(app)
    if panel is None:
        return
    draft = panel.read_qa_draft()
    messages = collect_recent_messages(app, 50)
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
    error = parse_error or normalized_scope.error
    question = draft.question.strip()
    if not question:
        error = "question is required"
    body = "Ready to ask scoped Q&A." if not error else ""
    text = render_qa_result_text(
        app,
        question=question or "(empty)",
        scope_mode=normalized_scope.scope.mode,
        selected_indices=normalized_scope.selected_indices,
        estimate=estimate,
        body=body,
        prefix="pre-send estimate",
        error=error,
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
    if not messages:
        error = "no captured messages available"

    if error:
        text = render_qa_result_text(
            app,
            question=question or "(empty)",
            scope_mode=normalized_scope.scope.mode,
            selected_indices=normalized_scope.selected_indices,
            estimate=estimate,
            body="",
            prefix="scoped Q&A blocked",
            error=error,
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
            question=question,
            scope_mode=normalized_scope.scope.mode,
            selected_indices=normalized_scope.selected_indices,
            estimate=estimate,
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
            question=question,
            scope=scope,
            source_provider=source_provider,
            request_id=request_id,
        )
        app.call_from_thread(
            app._on_side_channel_qa_result,
            result,
            question,
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


def render_action_candidates_text(
    app,
    *,
    batch_id: str,
    items: list[object],
    source: str,
    error: str = "",
) -> str:
    lines = [
        "action extraction review",
        f"batch: {batch_id}",
        f"source: {source}",
        f"candidate_count: {len(items)}",
    ]
    if error:
        lines.append(f"error: {error}")
    if not items:
        lines.append("No action/deferred candidates found.")
        return "\n".join(lines)

    lines.extend(["", "candidates:"])
    for index, item in enumerate(items):
        kind = str(getattr(item, "kind", "action"))
        text = str(getattr(item, "text", "")).strip()
        confidence = float(getattr(item, "confidence", 0.0))
        source_links = getattr(item, "source_links", []) or []
        link_parts = [
            "{}:{}".format(
                str(getattr(link, "request_id", "")),
                int(getattr(link, "message_index", -1)),
            )
            for link in source_links
        ]
        source_text = ", ".join(link_parts) if link_parts else "(none)"
        lines.append(
            "{}. [{}] {} (confidence={:.2f}) sources={}".format(
                index,
                kind,
                text,
                confidence,
                source_text,
            )
        )

    lines.extend(
        [
            "",
            "review inputs:",
            "- set accept indices and reject indices in Action Review controls",
            "- click Apply Review to confirm explicit accept/reject",
        ]
    )
    return "\n".join(lines)


def action_sc_action_extract(app) -> None:
    if app._view_store.get("sc:loading"):
        return
    context_session_key = app._active_context_session_key()
    if app._data_dispatcher is None:
        set_side_channel_result(
            app,
            text="action extraction blocked\nerror: dispatcher unavailable",
            source="fallback",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        return

    messages = collect_recent_messages(app, 50)
    if not messages:
        set_side_channel_result(
            app,
            text="action extraction blocked\nerror: no captured messages available",
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
        text="Running action extraction…",
        source="preview",
        elapsed_ms=0,
        loading=True,
        active_action="action_extract",
        context_session_key=context_session_key,
    )
    dispatcher = app._data_dispatcher
    source_provider = cc_dump.providers.session_provider(
        app._active_session_key_from_tabs(),
        default_session_key=app._default_session_key,
    )
    request_id = f"sc-action-{int(time.time() * 1000)}"

    def _do_action_extract() -> None:
        result = dispatcher.extract_action_items(
            messages,
            source_provider=source_provider,
            request_id=request_id,
        )
        app.call_from_thread(
            app._on_side_channel_action_extract_result,
            result,
            context_session_key,
        )

    app.run_worker(_do_action_extract, thread=True, exclusive=False)


def on_side_channel_action_extract_result(app, result, context_session_key: str) -> None:
    app._sc_action_batch_id = str(result.batch_id or "")
    app._sc_action_items = list(result.items or [])
    text = render_action_candidates_text(
        app,
        batch_id=app._sc_action_batch_id,
        items=app._sc_action_items,
        source=result.source,
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


def _review_parse_indices(app, draft) -> tuple[tuple[int, ...], tuple[int, ...], str]:
    accept_indices, accept_error = cc_dump.tui.side_channel_panel.parse_review_indices(
        draft.accept_indices_text
    )
    reject_indices, reject_error = cc_dump.tui.side_channel_panel.parse_review_indices(
        draft.reject_indices_text
    )
    parse_error = accept_error or reject_error
    return accept_indices, reject_indices, parse_error


def _review_validate_indices(
    *,
    items: list[object],
    accept_indices: tuple[int, ...],
    reject_indices: tuple[int, ...],
) -> str:
    if not accept_indices and not reject_indices:
        return "provide explicit accept and/or reject indices"

    max_index = len(items) - 1
    all_requested = tuple(sorted(set(accept_indices) | set(reject_indices)))
    out_of_range = [idx for idx in all_requested if idx < 0 or idx > max_index]
    if out_of_range:
        return f"indices out of range for candidate_count={len(items)}: {out_of_range}"

    overlap = sorted(set(accept_indices) & set(reject_indices))
    if overlap:
        return f"indices overlap between accept/reject: {overlap}"
    return ""


def _format_action_review_result(
    *,
    batch_id: str,
    accepted: list[object],
    rejected_items: list[object],
    remaining_count: int,
    beads_enabled: bool,
) -> str:
    lines = [
        "action review applied",
        f"batch: {batch_id}",
        f"accepted_count: {len(accepted)}",
        f"rejected_count: {len(rejected_items)}",
        f"beads_enabled: {beads_enabled}",
        "",
        "accepted:",
    ]
    if not accepted:
        lines.append("- (none)")
    for item in accepted:
        beads_id = str(getattr(item, "beads_issue_id", "") or "")
        beads_suffix = f" beads={beads_id}" if beads_id else ""
        lines.append(f"- [{item.kind}] {item.text}{beads_suffix}")

    lines.extend(["", "rejected:"])
    if not rejected_items:
        lines.append("- (none)")
    for item in rejected_items:
        lines.append(f"- [{getattr(item, 'kind', 'action')}] {getattr(item, 'text', '')}")
    lines.extend(["", f"remaining_candidates: {remaining_count}"])
    return "\n".join(lines)


def _blocked_apply_review(app, message: str) -> None:
    set_side_channel_result(
        app,
        text=f"apply review blocked\nerror: {message}",
        source="fallback",
        elapsed_ms=0,
        loading=False,
        active_action="",
        focus_results=True,
    )


def _apply_review_prerequisite_error(app) -> str:
    if app._data_dispatcher is None:
        return "dispatcher unavailable"
    if not app._sc_action_batch_id:
        return "run Extract Actions first"
    return ""


def _resolve_action_review_inputs(
    app,
    panel,
    *,
    items: list[object],
) -> tuple[object, tuple[int, ...], tuple[int, ...], str]:
    draft = panel.read_action_review_draft()
    accept_indices, reject_indices, parse_error = _review_parse_indices(app, draft)
    validation_error = _review_validate_indices(
        items=items,
        accept_indices=accept_indices,
        reject_indices=reject_indices,
    )
    return (draft, accept_indices, reject_indices, parse_error or validation_error)


def _item_ids_at_indices(items: list[object], indices: tuple[int, ...]) -> list[str]:
    return [str(getattr(items[idx], "item_id", "")) for idx in indices]


def _items_at_indices(items: list[object], indices: tuple[int, ...]) -> list[object]:
    return [items[idx] for idx in indices]


def _remaining_items_after_review(
    items: list[object],
    *,
    accept_indices: tuple[int, ...],
    reject_indices: tuple[int, ...],
) -> list[object]:
    resolved_indices = set(accept_indices) | set(reject_indices)
    return [item for idx, item in enumerate(items) if idx not in resolved_indices]


def action_sc_action_apply_review(app) -> None:
    panel = get_side_channel_panel_widget(app)
    if panel is None:
        return
    blocked_reason = _apply_review_prerequisite_error(app)
    if blocked_reason:
        _blocked_apply_review(app, blocked_reason)
        return

    items = list(app._sc_action_items)
    draft, accept_indices, reject_indices, review_error = _resolve_action_review_inputs(
        app,
        panel,
        items=items,
    )
    if review_error:
        _blocked_apply_review(app, review_error)
        return

    accepted_item_ids = _item_ids_at_indices(items, accept_indices)
    beads_enabled = bool(draft.create_beads and accepted_item_ids)
    accepted = app._data_dispatcher.accept_action_items(
        batch_id=app._sc_action_batch_id,
        item_ids=accepted_item_ids,
        create_beads=beads_enabled,
    )

    rejected_items = _items_at_indices(items, reject_indices)
    app._sc_action_items = _remaining_items_after_review(
        items,
        accept_indices=accept_indices,
        reject_indices=reject_indices,
    )

    set_side_channel_result(
        app,
        text=_format_action_review_result(
            batch_id=app._sc_action_batch_id,
            accepted=accepted,
            rejected_items=rejected_items,
            remaining_count=len(app._sc_action_items),
            beads_enabled=beads_enabled,
        ),
        source="preview",
        elapsed_ms=0,
        loading=False,
        active_action="",
        focus_results=True,
    )


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


def action_sc_preview_action_review(app) -> None:
    action_sc_action_extract(app)


def action_sc_preview_handoff(app) -> None:
    workbench_preview(app, "Handoff Draft", "cc-dump-mjb.4")


def action_sc_preview_utilities(app) -> None:
    action_sc_utility_run(app)
