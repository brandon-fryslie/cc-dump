import json

import pytest

from cc_dump.har_checkpoint_diff import (
    diff_checkpoints,
    render_diff_markdown,
    snapshot_from_har_entry,
)


def _make_entry(
    *,
    session_id: str,
    model: str,
    messages: list[dict],
    input_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    output_tokens: int,
    started: str = "2026-02-11T00:00:00+00:00",
) -> dict:
    request = {
        "model": model,
        "messages": messages,
        "metadata": {
            "user_id": (
                "user_abc_account_def_session_"
                + session_id
            )
        },
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
        "startedDateTime": started,
        "request": {"postData": {"text": json.dumps(request)}},
        "response": {"content": {"text": json.dumps(response)}},
    }


def test_diff_detects_appended_directives_and_command_loops():
    before_messages = [
        {"role": "user", "content": "Please write a test first."},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "uv run pytest tests/test_dump.py -xvs"},
                },
                {"type": "text", "text": "Running tests now."},
            ],
        },
    ]
    after_messages = before_messages + [
        {"role": "user", "content": "Do NOT add fallbacks. Reproduce exact error."},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "uv run pytest tests/test_dump.py -xvs"},
                },
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "uv run pytest tests/test_dump.py -xvs"},
                },
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/cc_dump/dump.py"}},
                {"type": "text", "text": "Reproduced failure. Adjusting approach."},
            ],
        },
    ]
    before = snapshot_from_har_entry(
        _make_entry(
            session_id="sess-1",
            model="claude-sonnet-4-5",
            messages=before_messages,
            input_tokens=10,
            cache_read_tokens=90,
            cache_creation_tokens=5,
            output_tokens=120,
        ),
        10,
    )
    after = snapshot_from_har_entry(
        _make_entry(
            session_id="sess-1",
            model="claude-sonnet-4-5",
            messages=after_messages,
            input_tokens=5,
            cache_read_tokens=150,
            cache_creation_tokens=2,
            output_tokens=80,
            started="2026-02-11T00:01:00+00:00",
        ),
        43,
    )

    diff = diff_checkpoints(before, after)

    assert diff.appended_messages == 2
    assert diff.comparison_mode == "append_only"
    assert diff.dropped_messages_from_before == 0
    assert "Do NOT add fallbacks. Reproduce exact error." in diff.appended_user_messages
    assert diff.repeated_commands["uv run pytest tests/test_dump.py -xvs"] == 2
    assert diff.appended_tool_counts["Bash"] == 2
    assert diff.appended_tool_counts["Edit"] == 1
    assert any("retry loop signal" in insight for insight in diff.insights)
    markdown = render_diff_markdown(diff)
    assert "# Checkpoint Diff 10 -> 43" in markdown
    assert "Repeated Commands (Loop Signal)" in markdown


def test_diff_rejects_cross_session_comparison():
    one = snapshot_from_har_entry(
        _make_entry(
            session_id="sess-1",
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "a"}],
            input_tokens=1,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            output_tokens=1,
        ),
        0,
    )
    two = snapshot_from_har_entry(
        _make_entry(
            session_id="sess-2",
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
            input_tokens=1,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            output_tokens=1,
        ),
        1,
    )

    with pytest.raises(ValueError, match="same session_id"):
        diff_checkpoints(one, two)


def test_diff_marks_divergent_history_when_prefix_changes():
    before = snapshot_from_har_entry(
        _make_entry(
            session_id="sess-1",
            model="claude-sonnet-4-5",
            messages=[
                {"role": "user", "content": "original message"},
                {"role": "assistant", "content": "original reply"},
            ],
            input_tokens=1,
            cache_read_tokens=10,
            cache_creation_tokens=0,
            output_tokens=1,
        ),
        2,
    )
    after = snapshot_from_har_entry(
        _make_entry(
            session_id="sess-1",
            model="claude-sonnet-4-5",
            messages=[
                {"role": "user", "content": "replacement message"},
                {"role": "assistant", "content": "new reply"},
            ],
            input_tokens=1,
            cache_read_tokens=12,
            cache_creation_tokens=0,
            output_tokens=1,
        ),
        3,
    )
    diff = diff_checkpoints(before, after)
    assert diff.comparison_mode == "divergent"
    assert diff.dropped_messages_from_before == 2
    assert any("diverged" in insight for insight in diff.insights)
