"""Decision ledger schema and merge semantics.

// [LAW:one-type-per-behavior] A single canonical decision entry type.
// [LAW:one-source-of-truth] Ledger merge/update semantics are centralized here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


DecisionStatus = Literal["proposed", "accepted", "revised", "deprecated"]


@dataclass(frozen=True)
class DecisionSourceLink:
    request_id: str = ""
    message_index: int = -1


@dataclass
class DecisionLedgerEntry:
    decision_id: str
    statement: str
    rationale: str = ""
    alternatives: list[str] = field(default_factory=list)
    consequences: list[str] = field(default_factory=list)
    status: DecisionStatus = "proposed"
    source_links: list[DecisionSourceLink] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def normalize_entry(raw: dict, *, request_id: str = "") -> DecisionLedgerEntry | None:
    """Normalize one raw decision dict into canonical ledger entry."""
    if not isinstance(raw, dict):
        return None
    statement = str(raw.get("statement", "")).strip()
    if not statement:
        return None
    decision_id = str(raw.get("decision_id", "")).strip() or _stable_decision_id(statement)
    status_raw = str(raw.get("status", "proposed")).strip().lower()
    status: DecisionStatus = (
        status_raw if status_raw in {"proposed", "accepted", "revised", "deprecated"} else "proposed"
    )  # type: ignore[assignment]
    alternatives = _string_list(raw.get("alternatives"))
    consequences = _string_list(raw.get("consequences"))
    supersedes = _string_list(raw.get("supersedes"))
    source_links = _normalize_source_links(raw.get("source_links"), request_id=request_id)
    now = datetime.now(timezone.utc).isoformat()
    return DecisionLedgerEntry(
        decision_id=decision_id,
        statement=statement,
        rationale=str(raw.get("rationale", "")).strip(),
        alternatives=alternatives,
        consequences=consequences,
        status=status,
        source_links=source_links,
        supersedes=supersedes,
        created_at=now,
        updated_at=now,
    )


def parse_decision_entries(text: str, *, request_id: str = "") -> list[DecisionLedgerEntry]:
    """Parse structured decision extraction JSON into canonical entries.

    Expected shape:
    {"decisions":[{...}]}
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("decisions", [])
    else:
        rows = []
    if not isinstance(rows, list):
        return []
    normalized: list[DecisionLedgerEntry] = []
    for raw in rows:
        entry = normalize_entry(raw, request_id=request_id)
        if entry is not None:
            normalized.append(entry)
    return normalized


class DecisionLedgerStore:
    """In-memory decision ledger with supersede/update semantics."""

    def __init__(self) -> None:
        self._entries: dict[str, DecisionLedgerEntry] = {}

    def upsert_many(self, entries: list[DecisionLedgerEntry]) -> list[DecisionLedgerEntry]:
        """Upsert a batch and apply supersede links deterministically."""
        for entry in entries:
            existing = self._entries.get(entry.decision_id)
            created_at = existing.created_at if existing is not None else entry.created_at
            merged = DecisionLedgerEntry(
                decision_id=entry.decision_id,
                statement=entry.statement,
                rationale=entry.rationale,
                alternatives=list(entry.alternatives),
                consequences=list(entry.consequences),
                status=entry.status,
                source_links=list(entry.source_links),
                supersedes=list(entry.supersedes),
                superseded_by=existing.superseded_by if existing is not None else "",
                created_at=created_at,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            self._entries[entry.decision_id] = merged

        for entry in entries:
            for old_id in entry.supersedes:
                old = self._entries.get(old_id)
                if old is None:
                    continue
                self._entries[old_id] = DecisionLedgerEntry(
                    decision_id=old.decision_id,
                    statement=old.statement,
                    rationale=old.rationale,
                    alternatives=list(old.alternatives),
                    consequences=list(old.consequences),
                    status="deprecated",
                    source_links=list(old.source_links),
                    supersedes=list(old.supersedes),
                    superseded_by=entry.decision_id,
                    created_at=old.created_at,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )

        return [self._entries[e.decision_id] for e in entries if e.decision_id in self._entries]

    def snapshot(self) -> list[DecisionLedgerEntry]:
        return sorted(self._entries.values(), key=lambda e: (e.created_at, e.decision_id))


def _stable_decision_id(statement: str) -> str:
    return "dec_" + hashlib.sha256(statement.encode("utf-8")).hexdigest()[:12]


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _normalize_source_links(raw: object, *, request_id: str) -> list[DecisionSourceLink]:
    if not isinstance(raw, list):
        return []
    links: list[DecisionSourceLink] = []
    for item in raw:
        if isinstance(item, int):
            links.append(DecisionSourceLink(request_id=request_id, message_index=item))
            continue
        if not isinstance(item, dict):
            continue
        message_index = item.get("message_index", -1)
        try:
            message_idx_int = int(message_index)
        except (TypeError, ValueError):
            continue
        links.append(
            DecisionSourceLink(
                request_id=str(item.get("request_id", "") or request_id),
                message_index=message_idx_int,
            )
        )
    return links
