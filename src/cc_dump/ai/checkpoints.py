"""Checkpoint artifacts and deterministic diff rendering.

// [LAW:one-type-per-behavior] One canonical checkpoint artifact type.
// [LAW:one-source-of-truth] Checkpoint schema + diff semantics are centralized here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import difflib


@dataclass(frozen=True)
class CheckpointArtifact:
    checkpoint_id: str
    purpose: str
    prompt_version: str
    source_provider: str
    request_id: str
    source_start: int
    source_end: int
    summary_text: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict) -> "CheckpointArtifact":
        return CheckpointArtifact(
            checkpoint_id=str(raw.get("checkpoint_id", "")),
            purpose=str(raw.get("purpose", "checkpoint_summary")),
            prompt_version=str(raw.get("prompt_version", "v1")),
            source_provider=str(raw.get("source_provider", "")),
            request_id=str(raw.get("request_id", "")),
            source_start=int(raw.get("source_start", 0)),
            source_end=int(raw.get("source_end", -1)),
            summary_text=str(raw.get("summary_text", "")),
            created_at=str(raw.get("created_at", "")),
        )


def make_checkpoint_id(
    *,
    source_provider: str,
    request_id: str,
    source_start: int,
    source_end: int,
    summary_text: str,
) -> str:
    basis = "|".join(
        [
            source_provider,
            request_id,
            str(source_start),
            str(source_end),
            summary_text,
        ]
    )
    return "chk_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


class CheckpointStore:
    """In-memory checkpoint artifact store."""

    def __init__(self) -> None:
        self._artifacts: dict[str, CheckpointArtifact] = {}

    def add(self, artifact: CheckpointArtifact) -> CheckpointArtifact:
        self._artifacts[artifact.checkpoint_id] = artifact
        return artifact

    def get(self, checkpoint_id: str) -> CheckpointArtifact | None:
        return self._artifacts.get(checkpoint_id)

    def snapshot(self) -> list[CheckpointArtifact]:
        return sorted(
            self._artifacts.values(),
            key=lambda artifact: (artifact.created_at, artifact.checkpoint_id),
        )


def create_checkpoint_artifact(
    *,
    purpose: str,
    prompt_version: str,
    source_provider: str,
    request_id: str,
    source_start: int,
    source_end: int,
    summary_text: str,
) -> CheckpointArtifact:
    return CheckpointArtifact(
        checkpoint_id=make_checkpoint_id(
            source_provider=source_provider,
            request_id=request_id,
            source_start=source_start,
            source_end=source_end,
            summary_text=summary_text,
        ),
        purpose=purpose,
        prompt_version=prompt_version,
        source_provider=source_provider,
        request_id=request_id,
        source_start=source_start,
        source_end=source_end,
        summary_text=summary_text,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def render_checkpoint_diff(
    *,
    before: CheckpointArtifact,
    after: CheckpointArtifact,
) -> str:
    """Render deterministic unified diff linked to checkpoint IDs."""
    before_lines = before.summary_text.splitlines()
    after_lines = after.summary_text.splitlines()
    diff_lines = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=before.checkpoint_id,
            tofile=after.checkpoint_id,
            lineterm="",
        )
    )
    body = "\n".join(diff_lines) if diff_lines else "(no summary changes)"
    return (
        f"checkpoint_diff:{before.checkpoint_id}->{after.checkpoint_id}\n"
        f"source_ranges:{before.source_start}-{before.source_end}|{after.source_start}-{after.source_end}\n"
        f"{body}"
    )
