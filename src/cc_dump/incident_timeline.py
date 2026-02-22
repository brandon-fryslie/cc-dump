"""Incident/debug timeline artifacts and rendering.

// [LAW:one-source-of-truth] Timeline schema, parsing, and render contract live here.
// [LAW:one-type-per-behavior] Facts and hypotheses share one entry type with a `kind` field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json


@dataclass(frozen=True)
class TimelineSourceLink:
    request_id: str
    message_index: int

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "message_index": self.message_index,
        }


@dataclass(frozen=True)
class TimelineEntry:
    kind: str  # "fact" | "hypothesis"
    timestamp: str
    actor: str
    action: str
    outcome: str
    source_links: list[TimelineSourceLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action,
            "outcome": self.outcome,
            "source_links": [link.to_dict() for link in self.source_links],
        }


@dataclass(frozen=True)
class IncidentTimelineArtifact:
    timeline_id: str
    purpose: str
    prompt_version: str
    source_session_id: str
    request_id: str
    source_start: int
    source_end: int
    facts: list[TimelineEntry]
    hypotheses: list[TimelineEntry]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "timeline_id": self.timeline_id,
            "purpose": self.purpose,
            "prompt_version": self.prompt_version,
            "source_session_id": self.source_session_id,
            "request_id": self.request_id,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "facts": [entry.to_dict() for entry in self.facts],
            "hypotheses": [entry.to_dict() for entry in self.hypotheses],
            "created_at": self.created_at,
        }


def parse_incident_timeline_artifact(
    text: str,
    *,
    purpose: str,
    prompt_version: str,
    source_session_id: str,
    request_id: str,
    source_start: int,
    source_end: int,
    include_hypotheses: bool,
) -> IncidentTimelineArtifact:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = {}
    facts = _parse_entries(raw.get("facts", []), kind="fact", request_id=request_id)
    hypotheses = _parse_entries(raw.get("hypotheses", []), kind="hypothesis", request_id=request_id)
    facts = sorted(facts, key=lambda entry: (entry.timestamp, entry.actor, entry.action, entry.outcome))
    hypotheses = sorted(hypotheses, key=lambda entry: (entry.timestamp, entry.actor, entry.action, entry.outcome))
    if not include_hypotheses:
        hypotheses = []
    timeline_id = _make_timeline_id(
        source_session_id=source_session_id,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        facts=facts,
        hypotheses=hypotheses,
    )
    return IncidentTimelineArtifact(
        timeline_id=timeline_id,
        purpose=purpose,
        prompt_version=prompt_version,
        source_session_id=source_session_id,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        facts=facts,
        hypotheses=hypotheses,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def fallback_incident_timeline_artifact(
    *,
    purpose: str,
    prompt_version: str,
    source_session_id: str,
    request_id: str,
    source_start: int,
    source_end: int,
    summary_text: str,
    include_hypotheses: bool,
) -> IncidentTimelineArtifact:
    facts = [
        TimelineEntry(
            kind="fact",
            timestamp="T+0",
            actor="system",
            action="fallback_summary",
            outcome=summary_text,
            source_links=[],
        )
    ]
    hypotheses = [] if not include_hypotheses else [
        TimelineEntry(
            kind="hypothesis",
            timestamp="T+0",
            actor="system",
            action="hypotheses_unavailable",
            outcome="No model-generated hypotheses available in fallback mode.",
            source_links=[],
        )
    ]
    timeline_id = _make_timeline_id(
        source_session_id=source_session_id,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        facts=facts,
        hypotheses=hypotheses,
    )
    return IncidentTimelineArtifact(
        timeline_id=timeline_id,
        purpose=purpose,
        prompt_version=prompt_version,
        source_session_id=source_session_id,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        facts=facts,
        hypotheses=hypotheses,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def render_incident_timeline_markdown(
    artifact: IncidentTimelineArtifact,
    *,
    include_hypotheses: bool,
) -> str:
    lines = [
        f"timeline:{artifact.timeline_id}",
        f"source_range:{artifact.source_start}-{artifact.source_end}",
        "## facts",
    ]
    if not artifact.facts:
        lines.append("- (none)")
    for entry in artifact.facts:
        lines.append(_render_entry(entry))
    if include_hypotheses:
        lines.append("## hypotheses")
        if not artifact.hypotheses:
            lines.append("- (none)")
        for entry in artifact.hypotheses:
            lines.append(_render_entry(entry))
    return "\n".join(lines)


class IncidentTimelineStore:
    """Stores latest incident timelines for scoped debug workflows."""

    def __init__(self) -> None:
        self._artifacts: dict[str, IncidentTimelineArtifact] = {}
        self._latest_by_session: dict[str, str] = {}
        self._latest_global_id: str = ""

    def add(self, artifact: IncidentTimelineArtifact) -> IncidentTimelineArtifact:
        self._artifacts[artifact.timeline_id] = artifact
        session_key = artifact.source_session_id or "__global__"
        self._latest_by_session[session_key] = artifact.timeline_id
        self._latest_global_id = artifact.timeline_id
        return artifact

    def latest(self, source_session_id: str = "") -> IncidentTimelineArtifact | None:
        session_key = source_session_id or "__global__"
        timeline_id = self._latest_by_session.get(session_key, self._latest_global_id)
        if not timeline_id:
            return None
        return self._artifacts.get(timeline_id)

    def snapshot(self) -> list[IncidentTimelineArtifact]:
        return sorted(
            self._artifacts.values(),
            key=lambda artifact: (artifact.created_at, artifact.timeline_id),
        )


def _parse_entries(raw_entries: object, *, kind: str, request_id: str) -> list[TimelineEntry]:
    if not isinstance(raw_entries, list):
        return []
    parsed: list[TimelineEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        timestamp = str(raw_entry.get("timestamp", "")).strip()
        actor = str(raw_entry.get("actor", "")).strip()
        action = str(raw_entry.get("action", "")).strip()
        outcome = str(raw_entry.get("outcome", "")).strip()
        if not timestamp or not actor or not action:
            continue
        parsed.append(
            TimelineEntry(
                kind=kind,
                timestamp=timestamp,
                actor=actor,
                action=action,
                outcome=outcome,
                source_links=_parse_source_links(raw_entry.get("source_links", []), request_id=request_id),
            )
        )
    return parsed


def _parse_source_links(raw_links: object, *, request_id: str) -> list[TimelineSourceLink]:
    if not isinstance(raw_links, list):
        return []
    parsed: list[TimelineSourceLink] = []
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            continue
        try:
            message_index = int(raw_link.get("message_index", -1))
        except (TypeError, ValueError):
            continue
        if message_index < 0:
            continue
        parsed.append(TimelineSourceLink(request_id=request_id, message_index=message_index))
    return parsed


def _render_entry(entry: TimelineEntry) -> str:
    refs = ", ".join(f"{link.request_id}:{link.message_index}" for link in entry.source_links)
    suffix = f" [src: {refs}]" if refs else ""
    return f"- [{entry.timestamp}] {entry.actor}: {entry.action} -> {entry.outcome}{suffix}"


def _make_timeline_id(
    *,
    source_session_id: str,
    request_id: str,
    source_start: int,
    source_end: int,
    facts: list[TimelineEntry],
    hypotheses: list[TimelineEntry],
) -> str:
    parts = [
        source_session_id,
        request_id,
        str(source_start),
        str(source_end),
    ]
    for entry in [*facts, *hypotheses]:
        parts.append(f"{entry.kind}|{entry.timestamp}|{entry.actor}|{entry.action}|{entry.outcome}")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return "timeline_" + digest
