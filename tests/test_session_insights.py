import json

from cc_dump.session_insights import build_session_insights
from cc_dump.ai.side_channel_marker import SideChannelMarker, prepend_marker


def _entry(
    *,
    session_id: str,
    idx: int,
    messages: list[dict],
    input_tokens: int = 1,
    cache_read_tokens: int = 10,
    cache_creation_tokens: int = 0,
    output_tokens: int = 1,
    model: str = "claude-sonnet-4-5",
) -> dict:
    request = {
        "model": model,
        "messages": messages,
        "metadata": {"user_id": f"user_abc_account_def_session_{session_id}"},
    }
    response = {
        "usage": {
            "input_tokens": input_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
            "output_tokens": output_tokens,
        }
    }
    return {
        "startedDateTime": f"2026-02-11T00:00:{idx:02d}+00:00",
        "request": {"postData": {"text": json.dumps(request)}},
        "response": {"content": {"text": json.dumps(response)}},
    }


def test_build_session_insights_emits_all_artifact_groups():
    base_user = {"role": "user", "content": "Need dump command done without fallback."}
    assistant_step = {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest tests/test_dump.py -xvs"}},
            {"type": "text", "text": "Implemented and tests passed."},
        ],
    }
    marker_text = prepend_marker(
        "Summarize this session.",
        SideChannelMarker(run_id="run-1", purpose="checkpoint_summary"),
    )
    side_channel_user = {"role": "user", "content": marker_text}
    entries = [
        _entry(session_id="sess-1", idx=0, messages=[base_user], input_tokens=3, cache_read_tokens=2),
        _entry(session_id="sess-1", idx=1, messages=[base_user, assistant_step], input_tokens=2, cache_read_tokens=8),
        _entry(
            session_id="sess-1",
            idx=2,
            messages=[base_user, assistant_step, side_channel_user],
            input_tokens=1,
            cache_read_tokens=9,
        ),
    ]

    artifacts = build_session_insights(entries)

    assert artifacts.session_id == "sess-1"
    assert len(artifacts.turn_metrics) == 3
    assert len(artifacts.rolling_degradation) == 3
    assert "recommended_cut_index" in artifacts.cut_recommendation
    assert "task_goal" in artifacts.seed_context
    assert "distilled_evidence" in artifacts.seed_context
    assert "primary" in artifacts.budget_by_purpose
    assert "checkpoint_summary" in artifacts.budget_by_purpose
    assert artifacts.budget_by_purpose["checkpoint_summary"]["runs"] == 1
    assert isinstance(artifacts.tool_activity_raw, tuple)
    assert "suites" in artifacts.test_suite_analysis
    assert artifacts.token_estimation_health["request_count"] == 3
    assert artifacts.token_estimation_health["estimator_overhead_tokens"] == 0


def test_turn_metrics_capture_append_only_deltas():
    user0 = {"role": "user", "content": "debug this"}
    assistant0 = {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest tests/test_dump.py -xvs"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest tests/test_dump.py -xvs"}},
            {"type": "text", "text": "retrying"},
        ],
    }
    entries = [
        _entry(session_id="sess-2", idx=0, messages=[user0]),
        _entry(session_id="sess-2", idx=1, messages=[user0, assistant0]),
    ]

    artifacts = build_session_insights(entries)
    latest = artifacts.turn_metrics[-1]
    assert latest.comparison_mode == "append_only"
    assert latest.command_count == 2
    assert latest.repeated_command_count == 2
    assert latest.dominant_command_family == "uv run pytest"
    assert (
        latest.reported_total_input_tokens
        == latest.input_tokens + latest.cache_read_tokens + latest.cache_creation_tokens
    )
    assert latest.estimated_input_tokens_adjusted == latest.estimated_input_tokens_tiktoken
    assert latest.estimator_overhead_tokens == 0


def test_tool_activity_tracks_rereads_and_test_retry_cost_buckets():
    user0 = {"role": "user", "content": "debug flaky test"}
    assistant1 = {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "read-1",
                "name": "Read",
                "input": {"file_path": "tests/test_flaky.py"},
            },
            {
                "type": "tool_use",
                "id": "pytest-1",
                "name": "Bash",
                "input": {"command": "uv run pytest tests/test_flaky.py -xvs"},
            },
        ],
    }
    user_result1 = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "read-1", "content": "file contents"},
            {"type": "tool_result", "tool_use_id": "pytest-1", "is_error": True, "content": "1 failed"},
        ],
    }
    assistant2 = {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "read-2",
                "name": "Read",
                "input": {"file_path": "tests/test_flaky.py"},
            },
            {
                "type": "tool_use",
                "id": "pytest-2",
                "name": "Bash",
                "input": {"command": "uv run pytest tests/test_flaky.py -xvs"},
            },
        ],
    }
    user_result2 = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "read-2", "content": "file contents"},
            {"type": "tool_result", "tool_use_id": "pytest-2", "content": "1 passed"},
        ],
    }
    entries = [
        _entry(session_id="sess-3", idx=0, messages=[user0], input_tokens=2, cache_read_tokens=8, output_tokens=4),
        _entry(
            session_id="sess-3",
            idx=1,
            messages=[user0, assistant1, user_result1],
            input_tokens=3,
            cache_read_tokens=9,
            output_tokens=5,
        ),
        _entry(
            session_id="sess-3",
            idx=2,
            messages=[user0, assistant1, user_result1, assistant2, user_result2],
            input_tokens=4,
            cache_read_tokens=10,
            output_tokens=6,
        ),
    ]
    artifacts = build_session_insights(entries)

    reads = [row for row in artifacts.tool_activity_raw if row.tool_name == "Read"]
    assert len(reads) == 2
    assert reads[0].primary_target == "tests/test_flaky.py"
    assert reads[0].target_repeat_index == 1
    assert reads[1].target_repeat_index == 2
    assert reads[1].is_repeat_target

    suites = artifacts.test_suite_analysis["suites"]
    suite = suites["pytest tests/test_flaky.py"]
    assert suite["run_count"] == 2
    assert suite["repeat_runs"] == 1
    assert suite["runs_after_failure"] == 1
    assert "rerun_token_cost_ambiguous" in artifacts.test_suite_analysis


def test_overhead_tokens_are_reflected_in_adjusted_delta():
    user0 = {"role": "user", "content": "tiny request"}
    entries = [
        _entry(
            session_id="sess-4",
            idx=0,
            messages=[user0],
            input_tokens=10,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            output_tokens=1,
        ),
    ]
    base = build_session_insights(entries, estimator_overhead_tokens=0)
    tuned = build_session_insights(entries, estimator_overhead_tokens=360)
    base_row = base.turn_metrics[0]
    tuned_row = tuned.turn_metrics[0]
    assert tuned_row.estimated_input_tokens_adjusted == base_row.estimated_input_tokens_tiktoken + 360
    assert tuned_row.input_token_delta_adjusted == base_row.input_token_delta + 360
    assert tuned.token_estimation_health["estimator_overhead_tokens"] == 360
