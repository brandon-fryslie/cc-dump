"""Offline subagent parent-log enrichment for historical analysis.

This module correlates runtime request/session data (from HAR request bodies)
with Claude subagent JSONL artifacts under `.claude/projects`.

It is intentionally offline-only and optional.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

import cc_dump.core.formatting
import cc_dump.pipeline.har_replayer


HARPair = tuple[dict, dict, int, dict, dict, str]


@dataclass(frozen=True)
class RuntimeSessionSummary:
    """Runtime session summary extracted from HAR request streams."""

    session_id: str
    request_count: int
    task_tool_use_ids: tuple[str, ...]


@dataclass(frozen=True)
class SubagentArtifact:
    """One parsed subagent JSONL artifact and its parent/session metadata."""

    parent_session_id: str
    artifact_session_id: str
    agent_id: str
    log_path: str
    parent_tool_use_id: str
    root_uuid: str
    event_count: int
    first_timestamp: str
    last_timestamp: str


@dataclass(frozen=True)
class EnrichedSubagentArtifact:
    """Subagent artifact annotated with runtime Task-correlation signal."""

    parent_session_id: str
    artifact_session_id: str
    agent_id: str
    log_path: str
    parent_tool_use_id: str
    root_uuid: str
    event_count: int
    first_timestamp: str
    last_timestamp: str
    matches_runtime_task: bool


@dataclass(frozen=True)
class EnrichedRuntimeSession:
    """Runtime session annotated with correlated subagent artifacts."""

    session_id: str
    request_count: int
    task_tool_use_ids: tuple[str, ...]
    unmatched_task_tool_use_ids: tuple[str, ...]
    subagents: tuple[EnrichedSubagentArtifact, ...]


@dataclass(frozen=True)
class SubagentEnrichmentReport:
    """Top-level offline enrichment result."""

    runtime_sessions: tuple[EnrichedRuntimeSession, ...]
    orphan_subagents: tuple[SubagentArtifact, ...]


def _extract_runtime_session_id(request_body: dict) -> str:
    """Extract Claude session UUID from request metadata.user_id."""
    metadata = request_body.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    user_id = metadata.get("user_id", "")
    if not isinstance(user_id, str) or not user_id:
        return ""
    parsed = cc_dump.core.formatting.parse_user_id(user_id)
    if not parsed:
        return ""
    session_id = parsed.get("session_id", "")
    return session_id if isinstance(session_id, str) else ""


def _extract_task_tool_use_ids(request_body: dict) -> set[str]:
    """Extract Task tool_use IDs from assistant messages."""
    messages = request_body.get("messages", [])
    if not isinstance(messages, list):
        return set()
    task_ids: set[str] = set()
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role", "") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type", "") != "tool_use":
                continue
            if block.get("name", "") != "Task":
                continue
            tool_use_id = block.get("id", "")
            if isinstance(tool_use_id, str) and tool_use_id:
                task_ids.add(tool_use_id)
    return task_ids


def build_runtime_sessions(har_pairs: list[HARPair]) -> tuple[RuntimeSessionSummary, ...]:
    """Build per-session runtime summaries from HAR pairs.

    // [LAW:one-source-of-truth] Runtime session/task lineage comes from HAR
    request bodies only.
    """
    counts: dict[str, int] = {}
    task_ids: dict[str, set[str]] = {}
    for _req_headers, request_body, _status, _resp_headers, _complete, _provider in har_pairs:
        session_id = _extract_runtime_session_id(request_body)
        if not session_id:
            continue
        counts[session_id] = counts.get(session_id, 0) + 1
        ids = task_ids.setdefault(session_id, set())
        ids.update(_extract_task_tool_use_ids(request_body))

    summaries = []
    for session_id in sorted(counts):
        summaries.append(
            RuntimeSessionSummary(
                session_id=session_id,
                request_count=counts[session_id],
                task_tool_use_ids=tuple(sorted(task_ids.get(session_id, set()))),
            )
        )
    return tuple(summaries)


def _first_non_empty_string(events: list[dict], key: str) -> str:
    for event in events:
        value = event.get(key, "")
        if isinstance(value, str) and value:
            return value
    return ""


def load_subagent_artifacts(claude_projects_root: str) -> tuple[SubagentArtifact, ...]:
    """Load subagent JSONL artifacts from `.claude/projects`.

    // [LAW:locality-or-seam] Offline ingestion seam is isolated in one module.
    """
    root = Path(os.path.expanduser(claude_projects_root))
    if not root.exists():
        return tuple()

    artifacts: list[SubagentArtifact] = []
    for jsonl_path in sorted(root.rglob("subagents/*.jsonl")):
        parent_session_id = (
            jsonl_path.parent.parent.name if jsonl_path.parent.name == "subagents" else ""
        )
        events: list[dict] = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
        if not events:
            continue

        artifact_session_id = _first_non_empty_string(events, "sessionId") or parent_session_id
        agent_id = _first_non_empty_string(events, "agentId")
        if not agent_id:
            stem = jsonl_path.stem
            agent_id = stem[len("agent-"):] if stem.startswith("agent-") else stem

        parent_tool_use_id = _first_non_empty_string(events, "parentToolUseID")
        root_uuid = ""
        for event in events:
            parent_uuid = event.get("parentUuid", "")
            uuid = event.get("uuid", "")
            if parent_uuid is None and isinstance(uuid, str) and uuid:
                root_uuid = uuid
                break

        timestamps = sorted(
            ts
            for ts in (event.get("timestamp", "") for event in events)
            if isinstance(ts, str) and ts
        )
        first_timestamp = timestamps[0] if timestamps else ""
        last_timestamp = timestamps[-1] if timestamps else ""

        artifacts.append(
            SubagentArtifact(
                parent_session_id=parent_session_id,
                artifact_session_id=artifact_session_id,
                agent_id=agent_id,
                log_path=str(jsonl_path),
                parent_tool_use_id=parent_tool_use_id,
                root_uuid=root_uuid,
                event_count=len(events),
                first_timestamp=first_timestamp,
                last_timestamp=last_timestamp,
            )
        )
    return tuple(artifacts)


def enrich_runtime_sessions(
    runtime_sessions: tuple[RuntimeSessionSummary, ...],
    subagent_artifacts: tuple[SubagentArtifact, ...],
) -> SubagentEnrichmentReport:
    """Correlate runtime sessions with subagent artifacts.

    // [LAW:dataflow-not-control-flow] Correlation is one fixed stage sequence:
    // index runtime -> attach matching artifacts -> emit orphans.
    """
    artifacts_by_session: dict[str, list[SubagentArtifact]] = {}
    for artifact in subagent_artifacts:
        artifacts_by_session.setdefault(artifact.parent_session_id, []).append(artifact)

    runtime_session_ids = {item.session_id for item in runtime_sessions}

    enriched_sessions: list[EnrichedRuntimeSession] = []
    for runtime in runtime_sessions:
        artifacts = sorted(
            artifacts_by_session.get(runtime.session_id, []),
            key=lambda item: item.log_path,
        )
        runtime_task_ids = set(runtime.task_tool_use_ids)
        matched_task_ids: set[str] = set()
        enriched_subagents: list[EnrichedSubagentArtifact] = []
        for artifact in artifacts:
            matches = bool(
                artifact.parent_tool_use_id and artifact.parent_tool_use_id in runtime_task_ids
            )
            if matches:
                matched_task_ids.add(artifact.parent_tool_use_id)
            enriched_subagents.append(
                EnrichedSubagentArtifact(
                    parent_session_id=artifact.parent_session_id,
                    artifact_session_id=artifact.artifact_session_id,
                    agent_id=artifact.agent_id,
                    log_path=artifact.log_path,
                    parent_tool_use_id=artifact.parent_tool_use_id,
                    root_uuid=artifact.root_uuid,
                    event_count=artifact.event_count,
                    first_timestamp=artifact.first_timestamp,
                    last_timestamp=artifact.last_timestamp,
                    matches_runtime_task=matches,
                )
            )

        unmatched = tuple(sorted(runtime_task_ids - matched_task_ids))
        enriched_sessions.append(
            EnrichedRuntimeSession(
                session_id=runtime.session_id,
                request_count=runtime.request_count,
                task_tool_use_ids=runtime.task_tool_use_ids,
                unmatched_task_tool_use_ids=unmatched,
                subagents=tuple(enriched_subagents),
            )
        )

    orphans = tuple(
        artifact
        for artifact in sorted(subagent_artifacts, key=lambda item: item.log_path)
        if artifact.parent_session_id not in runtime_session_ids
    )
    return SubagentEnrichmentReport(
        runtime_sessions=tuple(enriched_sessions),
        orphan_subagents=orphans,
    )


def build_subagent_enrichment_report(
    har_pairs: list[HARPair],
    claude_projects_root: str = "~/.claude/projects",
) -> SubagentEnrichmentReport:
    """Build a full offline enrichment report from HAR pairs and Claude logs."""
    runtime_sessions = build_runtime_sessions(har_pairs)
    artifacts = load_subagent_artifacts(claude_projects_root)
    return enrich_runtime_sessions(runtime_sessions, artifacts)


def build_subagent_enrichment_report_from_har(
    har_path: str,
    claude_projects_root: str = "~/.claude/projects",
) -> SubagentEnrichmentReport:
    """Load HAR file and build offline enrichment report."""
    pairs = cc_dump.pipeline.har_replayer.load_har(har_path)
    return build_subagent_enrichment_report(pairs, claude_projects_root)


def report_to_dict(report: SubagentEnrichmentReport) -> dict:
    """Convert report dataclasses to a JSON-serializable dict."""
    runtime_sessions = []
    for runtime in report.runtime_sessions:
        runtime_sessions.append(
            {
                "session_id": runtime.session_id,
                "request_count": runtime.request_count,
                "task_tool_use_ids": list(runtime.task_tool_use_ids),
                "unmatched_task_tool_use_ids": list(runtime.unmatched_task_tool_use_ids),
                "subagents": [
                    {
                        "parent_session_id": sub.parent_session_id,
                        "artifact_session_id": sub.artifact_session_id,
                        "agent_id": sub.agent_id,
                        "log_path": sub.log_path,
                        "parent_tool_use_id": sub.parent_tool_use_id,
                        "root_uuid": sub.root_uuid,
                        "event_count": sub.event_count,
                        "first_timestamp": sub.first_timestamp,
                        "last_timestamp": sub.last_timestamp,
                        "matches_runtime_task": sub.matches_runtime_task,
                    }
                    for sub in runtime.subagents
                ],
            }
        )

    orphan_subagents = [
        {
            "parent_session_id": artifact.parent_session_id,
            "artifact_session_id": artifact.artifact_session_id,
            "agent_id": artifact.agent_id,
            "log_path": artifact.log_path,
            "parent_tool_use_id": artifact.parent_tool_use_id,
            "root_uuid": artifact.root_uuid,
            "event_count": artifact.event_count,
            "first_timestamp": artifact.first_timestamp,
            "last_timestamp": artifact.last_timestamp,
        }
        for artifact in report.orphan_subagents
    ]
    return {
        "runtime_sessions": runtime_sessions,
        "orphan_subagents": orphan_subagents,
    }


def main() -> None:
    """Offline CLI for subagent enrichment report generation."""
    parser = argparse.ArgumentParser(
        description="Correlate HAR runtime sessions with .claude/projects subagent logs."
    )
    parser.add_argument("har", help="Path to HAR file")
    parser.add_argument(
        "--claude-projects-root",
        default="~/.claude/projects",
        help="Root directory for Claude project logs (default: ~/.claude/projects)",
    )
    args = parser.parse_args()

    report = build_subagent_enrichment_report_from_har(
        har_path=args.har,
        claude_projects_root=args.claude_projects_root,
    )
    print(json.dumps(report_to_dict(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
