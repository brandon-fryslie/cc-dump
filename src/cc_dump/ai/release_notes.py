"""Release-note/changelog artifacts, templates, and rendering.

// [LAW:one-source-of-truth] Release-note schema + template rendering centralized here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json


RELEASE_NOTE_SECTIONS: tuple[str, ...] = (
    "user_highlights",
    "technical_changes",
    "known_issues",
    "upgrade_notes",
)


@dataclass(frozen=True)
class ReleaseSourceLink:
    request_id: str
    message_index: int

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "message_index": self.message_index,
        }


@dataclass(frozen=True)
class ReleaseNoteEntry:
    title: str
    detail: str
    source_links: list[ReleaseSourceLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "detail": self.detail,
            "source_links": [link.to_dict() for link in self.source_links],
        }


@dataclass(frozen=True)
class ReleaseNotesArtifact:
    artifact_id: str
    purpose: str
    prompt_version: str
    source_session_id: str
    request_id: str
    source_start: int
    source_end: int
    sections: dict[str, list[ReleaseNoteEntry]]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "purpose": self.purpose,
            "prompt_version": self.prompt_version,
            "source_session_id": self.source_session_id,
            "request_id": self.request_id,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "sections": {
                name: [entry.to_dict() for entry in self.sections.get(name, [])]
                for name in RELEASE_NOTE_SECTIONS
            },
            "created_at": self.created_at,
        }


def parse_release_notes_artifact(
    text: str,
    *,
    purpose: str,
    prompt_version: str,
    source_session_id: str,
    request_id: str,
    source_start: int,
    source_end: int,
) -> ReleaseNotesArtifact:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = {}
    sections = _normalize_sections(raw.get("sections", {}), request_id=request_id)
    artifact_id = _make_artifact_id(
        source_session_id=source_session_id,
        request_id=request_id,
        prompt_version=prompt_version,
        source_start=source_start,
        source_end=source_end,
        sections=sections,
    )
    return ReleaseNotesArtifact(
        artifact_id=artifact_id,
        purpose=purpose,
        prompt_version=prompt_version,
        source_session_id=source_session_id,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        sections=sections,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def fallback_release_notes_artifact(
    *,
    purpose: str,
    prompt_version: str,
    source_session_id: str,
    request_id: str,
    source_start: int,
    source_end: int,
    summary_text: str,
) -> ReleaseNotesArtifact:
    sections = _empty_sections()
    sections["user_highlights"] = [
        ReleaseNoteEntry(
            title="Fallback summary",
            detail=summary_text,
            source_links=[],
        )
    ]
    artifact_id = _make_artifact_id(
        source_session_id=source_session_id,
        request_id=request_id,
        prompt_version=prompt_version,
        source_start=source_start,
        source_end=source_end,
        sections=sections,
    )
    return ReleaseNotesArtifact(
        artifact_id=artifact_id,
        purpose=purpose,
        prompt_version=prompt_version,
        source_session_id=source_session_id,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        sections=sections,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def render_release_notes_markdown(artifact: ReleaseNotesArtifact, *, variant: str) -> str:
    section_order = _variant_sections(variant)
    lines = [
        f"release_notes:{artifact.artifact_id}",
        f"prompt_version:{artifact.prompt_version}",
        f"variant:{variant}",
        f"source_range:{artifact.source_start}-{artifact.source_end}",
    ]
    for section_name in section_order:
        lines.append(f"## {section_name.replace('_', ' ')}")
        entries = artifact.sections.get(section_name, [])
        if not entries:
            lines.append("- (none)")
            continue
        for entry in entries:
            refs = ", ".join(f"{link.request_id}:{link.message_index}" for link in entry.source_links)
            ref_suffix = f" [src: {refs}]" if refs else ""
            lines.append(f"- {entry.title}: {entry.detail}{ref_suffix}")
    return "\n".join(lines)


class ReleaseNotesStore:
    """Stores generated release-note drafts for review/export handoff."""

    def __init__(self) -> None:
        self._artifacts: dict[str, ReleaseNotesArtifact] = {}
        self._latest_by_session: dict[str, str] = {}
        self._latest_global_id: str = ""

    def add(self, artifact: ReleaseNotesArtifact) -> ReleaseNotesArtifact:
        self._artifacts[artifact.artifact_id] = artifact
        session_key = artifact.source_session_id or "__global__"
        self._latest_by_session[session_key] = artifact.artifact_id
        self._latest_global_id = artifact.artifact_id
        return artifact

    def get(self, artifact_id: str) -> ReleaseNotesArtifact | None:
        return self._artifacts.get(artifact_id)

    def latest(self, source_session_id: str = "") -> ReleaseNotesArtifact | None:
        session_key = source_session_id or "__global__"
        artifact_id = self._latest_by_session.get(session_key, self._latest_global_id)
        if not artifact_id:
            return None
        return self._artifacts.get(artifact_id)

    def snapshot(self) -> list[ReleaseNotesArtifact]:
        return sorted(
            self._artifacts.values(),
            key=lambda artifact: (artifact.created_at, artifact.artifact_id),
        )


def _normalize_sections(raw_sections: object, *, request_id: str) -> dict[str, list[ReleaseNoteEntry]]:
    sections = _empty_sections()
    if not isinstance(raw_sections, dict):
        return sections
    for section_name in RELEASE_NOTE_SECTIONS:
        raw_entries = raw_sections.get(section_name, [])
        if not isinstance(raw_entries, list):
            continue
        parsed: list[ReleaseNoteEntry] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            title = str(raw_entry.get("title", "")).strip()
            detail = str(raw_entry.get("detail", "")).strip()
            if not title and not detail:
                continue
            parsed.append(
                ReleaseNoteEntry(
                    title=title or "(untitled)",
                    detail=detail or "(no detail)",
                    source_links=_parse_source_links(raw_entry.get("source_links", []), request_id=request_id),
                )
            )
        sections[section_name] = parsed
    return sections


def _parse_source_links(raw_links: object, *, request_id: str) -> list[ReleaseSourceLink]:
    if not isinstance(raw_links, list):
        return []
    parsed: list[ReleaseSourceLink] = []
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            continue
        try:
            message_index = int(raw_link.get("message_index", -1))
        except (TypeError, ValueError):
            continue
        if message_index < 0:
            continue
        parsed.append(ReleaseSourceLink(request_id=request_id, message_index=message_index))
    return parsed


def _empty_sections() -> dict[str, list[ReleaseNoteEntry]]:
    return {name: [] for name in RELEASE_NOTE_SECTIONS}


def _variant_sections(variant: str) -> tuple[str, ...]:
    if variant == "technical":
        return ("technical_changes", "known_issues", "upgrade_notes")
    return ("user_highlights", "known_issues", "upgrade_notes")


def _make_artifact_id(
    *,
    source_session_id: str,
    request_id: str,
    prompt_version: str,
    source_start: int,
    source_end: int,
    sections: dict[str, list[ReleaseNoteEntry]],
) -> str:
    parts = [
        source_session_id,
        request_id,
        prompt_version,
        str(source_start),
        str(source_end),
    ]
    for section_name in RELEASE_NOTE_SECTIONS:
        entries = sections.get(section_name, [])
        parts.append(section_name)
        for entry in entries:
            refs = ",".join(str(link.message_index) for link in entry.source_links)
            parts.append(f"{entry.title}|{entry.detail}|{refs}")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return "rel_" + digest
