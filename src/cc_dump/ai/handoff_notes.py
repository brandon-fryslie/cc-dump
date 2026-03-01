"""Structured handoff note artifacts and persistence for resume flows.

// [LAW:one-source-of-truth] Handoff template contract + parsing + persistence live here.
// [LAW:one-type-per-behavior] One artifact type serves all handoff purposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json


SECTION_ORDER: tuple[str, ...] = (
    "changed",
    "decisions",
    "open_work",
    "risks",
    "next_steps",
)


@dataclass(frozen=True)
class HandoffSourceLink:
    request_id: str
    message_index: int

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "message_index": self.message_index,
        }


@dataclass(frozen=True)
class HandoffEntry:
    text: str
    source_links: list[HandoffSourceLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "source_links": [link.to_dict() for link in self.source_links],
        }


@dataclass(frozen=True)
class HandoffArtifact:
    handoff_id: str
    purpose: str
    prompt_version: str
    source_provider: str
    request_id: str
    source_start: int
    source_end: int
    sections: dict[str, list[HandoffEntry]]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "handoff_id": self.handoff_id,
            "purpose": self.purpose,
            "prompt_version": self.prompt_version,
            "source_provider": self.source_provider,
            "request_id": self.request_id,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "sections": {
                name: [entry.to_dict() for entry in self.sections.get(name, [])]
                for name in SECTION_ORDER
            },
            "created_at": self.created_at,
        }


def parse_handoff_artifact(
    text: str,
    *,
    purpose: str,
    prompt_version: str,
    source_provider: str,
    request_id: str,
    source_start: int,
    source_end: int,
) -> HandoffArtifact:
    """Parse strict JSON payload into normalized handoff artifact."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = {}
    raw_sections = raw.get("sections", {})
    sections = _normalize_sections(raw_sections, request_id=request_id)
    handoff_id = _make_handoff_id(
        source_provider=source_provider,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        sections=sections,
    )
    return HandoffArtifact(
        handoff_id=handoff_id,
        purpose=purpose,
        prompt_version=prompt_version,
        source_provider=source_provider,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        sections=sections,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def fallback_handoff_artifact(
    *,
    purpose: str,
    prompt_version: str,
    source_provider: str,
    request_id: str,
    source_start: int,
    source_end: int,
    summary_text: str,
) -> HandoffArtifact:
    """Construct deterministic fallback handoff artifact with required sections."""
    sections = _empty_sections()
    sections["changed"] = [HandoffEntry(text=summary_text, source_links=[])]
    handoff_id = _make_handoff_id(
        source_provider=source_provider,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        sections=sections,
    )
    return HandoffArtifact(
        handoff_id=handoff_id,
        purpose=purpose,
        prompt_version=prompt_version,
        source_provider=source_provider,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        sections=sections,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def render_handoff_markdown(artifact: HandoffArtifact) -> str:
    lines = [
        f"handoff:{artifact.handoff_id}",
        f"source_range:{artifact.source_start}-{artifact.source_end}",
    ]
    for section_name in SECTION_ORDER:
        lines.append(f"## {section_name.replace('_', ' ')}")
        entries = artifact.sections.get(section_name, [])
        if not entries:
            lines.append("- (none)")
            continue
        for entry in entries:
            refs = ", ".join(
                f"{link.request_id}:{link.message_index}"
                for link in entry.source_links
            )
            suffix = f" [src: {refs}]" if refs else ""
            lines.append(f"- {entry.text}{suffix}")
    return "\n".join(lines)


class HandoffStore:
    """Stores latest handoff artifacts for resume continuity."""

    def __init__(self) -> None:
        self._artifacts: dict[str, HandoffArtifact] = {}
        self._by_provider: dict[str, str] = {}
        self._latest_global_id: str = ""

    def add(self, artifact: HandoffArtifact) -> HandoffArtifact:
        self._artifacts[artifact.handoff_id] = artifact
        provider_key = artifact.source_provider or "__global__"
        self._by_provider[provider_key] = artifact.handoff_id
        self._latest_global_id = artifact.handoff_id
        return artifact

    def latest(self, source_provider: str = "") -> HandoffArtifact | None:
        provider_key = source_provider or "__global__"
        handoff_id = self._by_provider.get(provider_key, self._latest_global_id)
        if not handoff_id:
            return None
        return self._artifacts.get(handoff_id)

    def snapshot(self) -> list[HandoffArtifact]:
        return sorted(
            self._artifacts.values(),
            key=lambda artifact: (artifact.created_at, artifact.handoff_id),
        )


def _normalize_sections(raw_sections: object, *, request_id: str) -> dict[str, list[HandoffEntry]]:
    sections = _empty_sections()
    if not isinstance(raw_sections, dict):
        return sections
    for section_name in SECTION_ORDER:
        raw_entries = raw_sections.get(section_name, [])
        if not isinstance(raw_entries, list):
            continue
        parsed_entries: list[HandoffEntry] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            text = str(raw_entry.get("text", "")).strip()
            if not text:
                continue
            parsed_entries.append(
                HandoffEntry(
                    text=text,
                    source_links=_parse_source_links(raw_entry.get("source_links", []), request_id=request_id),
                )
            )
        sections[section_name] = parsed_entries
    return sections


def _parse_source_links(raw_links: object, *, request_id: str) -> list[HandoffSourceLink]:
    if not isinstance(raw_links, list):
        return []
    parsed: list[HandoffSourceLink] = []
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            continue
        try:
            message_index = int(raw_link.get("message_index", -1))
        except (TypeError, ValueError):
            continue
        if message_index < 0:
            continue
        parsed.append(HandoffSourceLink(request_id=request_id, message_index=message_index))
    return parsed


def _empty_sections() -> dict[str, list[HandoffEntry]]:
    return {section_name: [] for section_name in SECTION_ORDER}


def _make_handoff_id(
    *,
    source_provider: str,
    request_id: str,
    source_start: int,
    source_end: int,
    sections: dict[str, list[HandoffEntry]],
) -> str:
    basis_parts: list[str] = [
        source_provider,
        request_id,
        str(source_start),
        str(source_end),
    ]
    for section_name in SECTION_ORDER:
        entries = sections.get(section_name, [])
        basis_parts.append(section_name)
        for entry in entries:
            refs = ",".join(
                str(link.message_index)
                for link in entry.source_links
            )
            basis_parts.append(f"{entry.text}|{refs}")
    digest = hashlib.sha256("|".join(basis_parts).encode("utf-8")).hexdigest()[:16]
    return "handoff_" + digest
