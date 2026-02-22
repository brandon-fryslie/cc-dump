from cc_dump.conversation_qa import (
    QAScope,
    SCOPE_SELECTED_RANGE,
    SCOPE_WHOLE_SESSION,
    estimate_qa_budget,
    normalize_scope,
    parse_qa_artifact,
    select_messages,
)


def test_whole_session_scope_requires_explicit_selection():
    normalized = normalize_scope(
        QAScope(mode=SCOPE_WHOLE_SESSION, explicit_whole_session=False),
        total_messages=5,
    )
    assert normalized.error == "whole-session scope requires explicit selection"
    assert normalized.selected_indices == ()


def test_default_scope_is_selected_range():
    normalized = normalize_scope(QAScope(), total_messages=20)
    assert normalized.scope.mode == SCOPE_SELECTED_RANGE
    assert normalized.selected_indices[0] == 0


def test_parse_qa_artifact_parses_sources():
    artifact = parse_qa_artifact(
        '{"answer":"Use the checkpoint API.","source_links":[{"message_index":3,"quote":"create_checkpoint(...)"},{"message_index":5,"quote":"render diff"}]}',
        purpose="conversation_qa",
        prompt_version="v1",
        question="How do I make checkpoints?",
        request_id="req-1",
        normalized_scope=normalize_scope(QAScope(source_start=0, source_end=9), total_messages=10),
    )
    assert artifact.answer == "Use the checkpoint API."
    assert len(artifact.source_links) == 2
    assert artifact.source_links[0].request_id == "req-1"


def test_budget_estimate_scales_with_selected_messages():
    estimate = estimate_qa_budget(
        question="What changed?",
        selected_messages=select_messages(
            [{"role": "assistant", "content": "a"} for _ in range(4)],
            normalize_scope(QAScope(source_start=0, source_end=3), total_messages=4),
        ),
        scope_mode=SCOPE_SELECTED_RANGE,
    )
    assert estimate.message_count == 4
    assert estimate.estimated_total_tokens >= estimate.estimated_input_tokens
