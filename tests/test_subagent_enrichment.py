"""Tests for offline subagent parent-log enrichment."""

from __future__ import annotations

import json
from pathlib import Path

from cc_dump.experiments.subagent_enrichment import (
    build_runtime_sessions,
    load_subagent_artifacts,
    enrich_runtime_sessions,
    build_subagent_enrichment_report_from_har,
    report_to_dict,
)


def _request_body(session_id: str, task_tool_use_id: str = "") -> dict:
    content = []
    if task_tool_use_id:
        content.append(
            {
                "type": "tool_use",
                "id": task_tool_use_id,
                "name": "Task",
                "input": {"description": "run"},
            }
        )
    return {
        "model": "claude-sonnet-4",
        "metadata": {
            "user_id": (
                f"user_deadbeef_account_11111111-1111-1111-1111-111111111111_"
                f"session_{session_id}"
            ),
        },
        "messages": [{"role": "assistant", "content": content}],
    }


def _har_pair(session_id: str, task_tool_use_id: str = "") -> tuple[dict, dict, int, dict, dict, str]:
    return (
        {"content-type": "application/json"},
        _request_body(session_id, task_tool_use_id),
        200,
        {"content-type": "application/json"},
        {"id": "msg_1", "type": "message", "content": [], "usage": {}},
        "anthropic",
    )


def test_build_runtime_sessions_extracts_session_and_task_ids():
    sess_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    sess_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    pairs = [
        _har_pair(sess_a, "task-1"),
        _har_pair(sess_a),
        _har_pair(sess_b, "task-2"),
    ]

    sessions = build_runtime_sessions(pairs)

    assert len(sessions) == 2
    assert sessions[0].session_id == sess_a
    assert sessions[0].request_count == 2
    assert sessions[0].task_tool_use_ids == ("task-1",)
    assert sessions[1].session_id == sess_b
    assert sessions[1].request_count == 1
    assert sessions[1].task_tool_use_ids == ("task-2",)


def test_load_subagent_artifacts_parses_parent_and_session_relationships(tmp_path: Path):
    log_dir = tmp_path / "project-a" / "sess-a" / "subagents"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "agent-a123.jsonl"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "parentUuid": None,
                        "uuid": "root-uuid",
                        "sessionId": "sess-a",
                        "agentId": "a123",
                        "parentToolUseID": "task-1",
                        "timestamp": "2026-02-21T10:00:00.000Z",
                    }
                ),
                json.dumps(
                    {
                        "parentUuid": "root-uuid",
                        "uuid": "child-uuid",
                        "sessionId": "sess-a",
                        "agentId": "a123",
                        "timestamp": "2026-02-21T10:01:00.000Z",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    artifacts = load_subagent_artifacts(str(tmp_path))

    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.parent_session_id == "sess-a"
    assert artifact.artifact_session_id == "sess-a"
    assert artifact.agent_id == "a123"
    assert artifact.parent_tool_use_id == "task-1"
    assert artifact.root_uuid == "root-uuid"
    assert artifact.event_count == 2
    assert artifact.first_timestamp == "2026-02-21T10:00:00.000Z"
    assert artifact.last_timestamp == "2026-02-21T10:01:00.000Z"


def test_enrich_runtime_sessions_correlates_and_flags_orphans(tmp_path: Path):
    sess_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    sess_orphan = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    runtime = build_runtime_sessions([_har_pair(sess_a, "task-1")])

    sess_a_dir = tmp_path / "project-a" / sess_a / "subagents"
    sess_a_dir.mkdir(parents=True)
    (sess_a_dir / "agent-a1.jsonl").write_text(
        json.dumps(
                {
                    "parentUuid": None,
                    "uuid": "u1",
                    "sessionId": sess_a,
                    "agentId": "a1",
                    "parentToolUseID": "task-1",
                    "timestamp": "2026-02-21T10:00:00.000Z",
                }
        )
        + "\n",
        encoding="utf-8",
    )

    orphan_dir = tmp_path / "project-b" / sess_orphan / "subagents"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "agent-b1.jsonl").write_text(
        json.dumps(
                {
                    "parentUuid": None,
                    "uuid": "u2",
                    "sessionId": sess_orphan,
                    "agentId": "b1",
                    "parentToolUseID": "task-x",
                    "timestamp": "2026-02-21T11:00:00.000Z",
                }
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = load_subagent_artifacts(str(tmp_path))
    report = enrich_runtime_sessions(runtime, artifacts)

    assert len(report.runtime_sessions) == 1
    enriched = report.runtime_sessions[0]
    assert enriched.session_id == sess_a
    assert enriched.unmatched_task_tool_use_ids == ()
    assert len(enriched.subagents) == 1
    assert enriched.subagents[0].matches_runtime_task is True

    assert len(report.orphan_subagents) == 1
    assert report.orphan_subagents[0].parent_session_id == sess_orphan


def test_build_report_from_har_file_end_to_end(tmp_path: Path):
    har_path = tmp_path / "recording.har"
    session_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    request_body = _request_body(session_id, task_tool_use_id="task-e2e")
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "postData": {"text": json.dumps(request_body)},
                    },
                    "response": {
                        "status": 200,
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "content": {
                            "text": json.dumps(
                                {
                                    "id": "msg_123",
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [{"type": "text", "text": "ok"}],
                                    "usage": {},
                                }
                            )
                        },
                    },
                }
            ],
        }
    }
    har_path.write_text(json.dumps(har), encoding="utf-8")

    log_dir = tmp_path / "projects" / "proj-a" / session_id / "subagents"
    log_dir.mkdir(parents=True)
    (log_dir / "agent-ae2e.jsonl").write_text(
        json.dumps(
            {
                "parentUuid": None,
                "uuid": "root-e2e",
                "sessionId": session_id,
                "agentId": "ae2e",
                "parentToolUseID": "task-e2e",
                "timestamp": "2026-02-21T12:00:00.000Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_subagent_enrichment_report_from_har(
        har_path=str(har_path),
        claude_projects_root=str(tmp_path / "projects"),
    )
    report_json = report_to_dict(report)

    assert len(report_json["runtime_sessions"]) == 1
    enriched = report_json["runtime_sessions"][0]
    assert enriched["session_id"] == session_id
    assert enriched["task_tool_use_ids"] == ["task-e2e"]
    assert len(enriched["subagents"]) == 1
    assert enriched["subagents"][0]["matches_runtime_task"] is True
