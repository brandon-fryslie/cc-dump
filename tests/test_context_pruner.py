import json

from cc_dump.context_pruner import (
    build_context_prune_plan,
    find_active_branch_range,
    select_session_snapshots,
)
from cc_dump.har_checkpoint_diff import snapshot_from_har_entry


def _entry(
    *,
    session_id: str,
    messages: list[dict],
    idx: int,
    input_tokens: int = 1,
    cache_read_tokens: int = 10,
    output_tokens: int = 1,
) -> dict:
    request = {
        "model": "claude-sonnet-4-5",
        "messages": messages,
        "metadata": {"user_id": f"user_abc_account_def_session_{session_id}"},
    }
    response = {
        "usage": {
            "input_tokens": input_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": 0,
            "output_tokens": output_tokens,
        }
    }
    return {
        "startedDateTime": f"2026-02-11T00:00:0{idx}+00:00",
        "request": {"postData": {"text": json.dumps(request)}},
        "response": {"content": {"text": json.dumps(response)}},
    }


def _snapshots(entries: list[dict]) -> list:
    return [snapshot_from_har_entry(entry, idx) for idx, entry in enumerate(entries)]


def test_context_pruner_cuts_tail_retry_noise():
    messages0 = [{"role": "user", "content": "Need dump command working."}]
    messages1 = messages0 + [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m fix"}},
                {"type": "text", "text": "Implemented fix and committed."},
            ],
        }
    ]
    messages2 = messages1 + [
        {"role": "user", "content": "[Request interrupted by user] do not add fallback"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest tests/test_dump.py -xvs"}},
                {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest tests/test_dump.py -xvs"}},
                {"type": "text", "text": "Trying again."},
            ],
        },
    ]
    messages3 = messages2 + [
        {"role": "user", "content": "[Request interrupted by user] still failing"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest tests/test_dump.py -xvs"}},
                {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest tests/test_dump.py -xvs"}},
                {"type": "text", "text": "Retry loop."},
            ],
        },
    ]
    snaps = _snapshots(
        [
            _entry(session_id="sess-1", messages=messages0, idx=0),
            _entry(session_id="sess-1", messages=messages1, idx=1),
            _entry(session_id="sess-1", messages=messages2, idx=2),
            _entry(session_id="sess-1", messages=messages3, idx=3),
        ]
    )
    plan = build_context_prune_plan(snaps)
    assert plan.recommended_cut_index == 1
    assert plan.dropped_entry_count == 2
    assert any("degradation" in line.lower() for line in plan.rationale)


def test_context_pruner_keeps_latest_when_quality_stays_positive():
    messages0 = [{"role": "user", "content": "Build summary cache."}]
    messages1 = messages0 + [{"role": "assistant", "content": "Implemented cache skeleton."}]
    messages2 = messages1 + [{"role": "assistant", "content": "Fixed tests, all tests pass."}]
    snaps = _snapshots(
        [
            _entry(session_id="sess-1", messages=messages0, idx=0),
            _entry(session_id="sess-1", messages=messages1, idx=1),
            _entry(session_id="sess-1", messages=messages2, idx=2),
        ]
    )
    plan = build_context_prune_plan(snaps)
    assert plan.recommended_cut_index == 2
    assert plan.dropped_entry_count == 0


def test_active_branch_starts_after_divergence():
    base = [{"role": "user", "content": "original"}]
    branch_a = base + [{"role": "assistant", "content": "a"}]
    branch_b = [{"role": "user", "content": "fork root"}]
    branch_b2 = branch_b + [{"role": "assistant", "content": "fork step 2"}]
    all_snaps = _snapshots(
        [
            _entry(session_id="sess-1", messages=base, idx=0),
            _entry(session_id="sess-1", messages=branch_a, idx=1),
            _entry(session_id="sess-1", messages=branch_b, idx=2),
            _entry(session_id="sess-1", messages=branch_b2, idx=3),
        ]
    )
    session_snaps = select_session_snapshots(all_snaps, session_id="sess-1")
    start, end = find_active_branch_range(session_snaps)
    assert (start, end) == (2, 3)
