"""Action/deferred extraction schema and review-state store.

// [LAW:one-type-per-behavior] One ActionWorkItem type handles both action/deferred via `kind`.
// [LAW:one-source-of-truth] Parsing + store semantics for extracted items are centralized here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import uuid
from collections.abc import Callable


@dataclass(frozen=True)
class ActionSourceLink:
    request_id: str
    message_index: int

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "message_index": self.message_index,
        }


@dataclass(frozen=True)
class ActionWorkItem:
    item_id: str
    kind: str  # "action" | "deferred"
    text: str
    confidence: float
    owner: str
    due_hint: str
    source_links: list[ActionSourceLink] = field(default_factory=list)
    status: str = "proposed"  # "proposed" | "accepted" | "rejected"
    beads_issue_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "text": self.text,
            "confidence": self.confidence,
            "owner": self.owner,
            "due_hint": self.due_hint,
            "source_links": [link.to_dict() for link in self.source_links],
            "status": self.status,
            "beads_issue_id": self.beads_issue_id,
            "created_at": self.created_at,
        }


def parse_action_items(text: str, *, request_id: str) -> list[ActionWorkItem]:
    """Parse strict JSON payload into normalized action/deferred items."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return []
    raw_items = raw.get("items", [])
    if not isinstance(raw_items, list):
        return []
    parsed: list[ActionWorkItem] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue
        item_text = str(raw_item.get("text", "")).strip()
        if not item_text:
            continue
        kind = str(raw_item.get("kind", "action")).strip().lower()
        if kind not in {"action", "deferred"}:
            kind = "action"
        try:
            confidence = float(raw_item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        source_links = _parse_source_links(raw_item.get("source_links", []), request_id=request_id)
        item_id = _make_item_id(
            request_id=request_id,
            list_index=index,
            kind=kind,
            text=item_text,
        )
        parsed.append(
            ActionWorkItem(
                item_id=item_id,
                kind=kind,
                text=item_text,
                confidence=confidence,
                owner=str(raw_item.get("owner", "")).strip(),
                due_hint=str(raw_item.get("due_hint", "")).strip(),
                source_links=source_links,
                status="proposed",
                beads_issue_id="",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    return parsed


def _parse_source_links(raw_links: object, *, request_id: str) -> list[ActionSourceLink]:
    links: list[ActionSourceLink] = []
    if not isinstance(raw_links, list):
        return links
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            continue
        try:
            message_index = int(raw_link.get("message_index", -1))
        except (TypeError, ValueError):
            continue
        if message_index < 0:
            continue
        links.append(ActionSourceLink(request_id=request_id, message_index=message_index))
    return links


def _make_item_id(*, request_id: str, list_index: int, kind: str, text: str) -> str:
    basis = f"{request_id}|{list_index}|{kind}|{text}"
    return "act_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


class ActionItemStore:
    """Pending-review and accepted action/deferred items."""

    def __init__(self) -> None:
        self._pending_batches: dict[str, list[ActionWorkItem]] = {}
        self._accepted: dict[str, ActionWorkItem] = {}

    def stage(self, items: list[ActionWorkItem]) -> str:
        batch_id = "batch_" + uuid.uuid4().hex[:12]
        self._pending_batches[batch_id] = list(items)
        return batch_id

    def pending(self, batch_id: str) -> list[ActionWorkItem]:
        return list(self._pending_batches.get(batch_id, []))

    def accepted_snapshot(self) -> list[ActionWorkItem]:
        return sorted(
            self._accepted.values(),
            key=lambda item: (item.created_at, item.item_id),
        )

    def accept(
        self,
        *,
        batch_id: str,
        item_ids: list[str],
        beads_hook: Callable[[ActionWorkItem], str] | None = None,
    ) -> list[ActionWorkItem]:
        pending_items = self._pending_batches.get(batch_id, [])
        accepted_ids = set(item_ids)
        accepted_items: list[ActionWorkItem] = []
        for item in pending_items:
            if item.item_id not in accepted_ids:
                continue
            beads_issue_id = beads_hook(item) if beads_hook is not None else ""
            accepted = ActionWorkItem(
                item_id=item.item_id,
                kind=item.kind,
                text=item.text,
                confidence=item.confidence,
                owner=item.owner,
                due_hint=item.due_hint,
                source_links=item.source_links,
                status="accepted",
                beads_issue_id=str(beads_issue_id or ""),
                created_at=item.created_at,
            )
            self._accepted[accepted.item_id] = accepted
            accepted_items.append(accepted)
        return accepted_items
