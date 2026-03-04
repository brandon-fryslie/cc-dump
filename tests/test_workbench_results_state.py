from cc_dump.tui.workbench_results_view import WorkbenchResultsView


def test_workbench_results_state_updates_without_mount():
    view = WorkbenchResultsView()

    view.update_result(
        text="summary",
        source="ai",
        elapsed_ms=42,
        action="qa_submit",
        context_session_id="session-1",
    )

    assert view.get_state() == {
        "text": "summary",
        "source": "ai",
        "elapsed_ms": 42,
        "action": "qa_submit",
        "context_session_id": "session-1",
        "meta": "context=session-1  source=ai  elapsed=42ms  action=qa_submit",
    }
