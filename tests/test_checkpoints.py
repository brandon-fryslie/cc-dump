from cc_dump.checkpoints import (
    CheckpointArtifact,
    make_checkpoint_id,
    render_checkpoint_diff,
)


def test_checkpoint_artifact_serialization_roundtrip():
    artifact = CheckpointArtifact(
        checkpoint_id="chk_123",
        purpose="checkpoint_summary",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-1",
        source_start=3,
        source_end=8,
        summary_text="summary",
        created_at="2026-02-22T00:00:00+00:00",
    )
    restored = CheckpointArtifact.from_dict(artifact.to_dict())
    assert restored == artifact


def test_checkpoint_id_is_deterministic():
    a = make_checkpoint_id(
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=2,
        summary_text="abc",
    )
    b = make_checkpoint_id(
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=2,
        summary_text="abc",
    )
    c = make_checkpoint_id(
        source_session_id="sess-1",
        request_id="req-2",
        source_start=0,
        source_end=2,
        summary_text="abc",
    )
    assert a == b
    assert a != c
    assert a.startswith("chk_")


def test_checkpoint_diff_is_deterministic_and_source_linked():
    before = CheckpointArtifact(
        checkpoint_id="chk_before",
        purpose="checkpoint_summary",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-before",
        source_start=0,
        source_end=1,
        summary_text="line one\nline two",
        created_at="2026-02-22T00:00:00+00:00",
    )
    after = CheckpointArtifact(
        checkpoint_id="chk_after",
        purpose="checkpoint_summary",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-after",
        source_start=2,
        source_end=3,
        summary_text="line one\nline three",
        created_at="2026-02-22T00:01:00+00:00",
    )
    first = render_checkpoint_diff(before=before, after=after)
    second = render_checkpoint_diff(before=before, after=after)
    assert first == second
    assert "checkpoint_diff:chk_before->chk_after" in first
    assert "source_ranges:0-1|2-3" in first
