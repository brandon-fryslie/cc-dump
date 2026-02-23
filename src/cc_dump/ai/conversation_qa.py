"""Scoped conversation Q&A contracts, parsing, and budget estimates.

// [LAW:one-source-of-truth] Scope contract + QA response schema live in one module.
// [LAW:capabilities-over-context] Scope selects only needed messages; no omniscient default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math


SCOPE_SELECTED_RANGE = "selected_range"
SCOPE_SELECTED_INDICES = "selected_indices"
SCOPE_WHOLE_SESSION = "whole_session"


@dataclass(frozen=True)
class QAScope:
    mode: str = SCOPE_SELECTED_RANGE
    source_start: int = 0
    source_end: int = 9
    indices: tuple[int, ...] = ()
    explicit_whole_session: bool = False


@dataclass(frozen=True)
class QASourceLink:
    request_id: str
    message_index: int
    quote: str

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "message_index": self.message_index,
            "quote": self.quote,
        }


@dataclass(frozen=True)
class QAArtifact:
    qa_id: str
    purpose: str
    prompt_version: str
    question: str
    scope_mode: str
    selected_indices: tuple[int, ...]
    answer: str
    source_links: list[QASourceLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "qa_id": self.qa_id,
            "purpose": self.purpose,
            "prompt_version": self.prompt_version,
            "question": self.question,
            "scope_mode": self.scope_mode,
            "selected_indices": list(self.selected_indices),
            "answer": self.answer,
            "source_links": [link.to_dict() for link in self.source_links],
        }


@dataclass(frozen=True)
class QABudgetEstimate:
    scope_mode: str
    message_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int


@dataclass(frozen=True)
class NormalizedQAScope:
    scope: QAScope
    selected_indices: tuple[int, ...]
    error: str


def normalize_scope(scope: QAScope | None, *, total_messages: int) -> NormalizedQAScope:
    if scope is None:
        scope = QAScope()
    if total_messages <= 0:
        return NormalizedQAScope(scope=scope, selected_indices=(), error="")

    if scope.mode == SCOPE_WHOLE_SESSION:
        if not scope.explicit_whole_session:
            return NormalizedQAScope(
                scope=scope,
                selected_indices=(),
                error="whole-session scope requires explicit selection",
            )
        return NormalizedQAScope(
            scope=scope,
            selected_indices=tuple(range(total_messages)),
            error="",
        )

    if scope.mode == SCOPE_SELECTED_INDICES:
        indices = sorted({idx for idx in scope.indices if 0 <= idx < total_messages})
        return NormalizedQAScope(scope=scope, selected_indices=tuple(indices), error="")

    lower = max(0, min(scope.source_start, scope.source_end))
    upper = min(total_messages - 1, max(scope.source_start, scope.source_end))
    return NormalizedQAScope(
        scope=scope,
        selected_indices=tuple(range(lower, upper + 1)),
        error="",
    )


def select_messages(messages: list[dict], normalized_scope: NormalizedQAScope) -> list[dict]:
    return [messages[idx] for idx in normalized_scope.selected_indices]


def parse_qa_artifact(
    text: str,
    *,
    purpose: str,
    prompt_version: str,
    question: str,
    request_id: str,
    normalized_scope: NormalizedQAScope,
) -> QAArtifact:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = {}
    answer = str(raw.get("answer", "")).strip()
    if not answer:
        answer = text.strip() or "(no answer)"
    source_links = _parse_source_links(raw.get("source_links", []), request_id=request_id)
    qa_id = _make_qa_id(
        question=question,
        scope_mode=normalized_scope.scope.mode,
        selected_indices=normalized_scope.selected_indices,
        answer=answer,
    )
    return QAArtifact(
        qa_id=qa_id,
        purpose=purpose,
        prompt_version=prompt_version,
        question=question,
        scope_mode=normalized_scope.scope.mode,
        selected_indices=normalized_scope.selected_indices,
        answer=answer,
        source_links=source_links,
    )


def fallback_qa_artifact(
    *,
    purpose: str,
    prompt_version: str,
    question: str,
    normalized_scope: NormalizedQAScope,
    fallback_answer: str,
) -> QAArtifact:
    qa_id = _make_qa_id(
        question=question,
        scope_mode=normalized_scope.scope.mode,
        selected_indices=normalized_scope.selected_indices,
        answer=fallback_answer,
    )
    return QAArtifact(
        qa_id=qa_id,
        purpose=purpose,
        prompt_version=prompt_version,
        question=question,
        scope_mode=normalized_scope.scope.mode,
        selected_indices=normalized_scope.selected_indices,
        answer=fallback_answer,
        source_links=[],
    )


def render_qa_markdown(artifact: QAArtifact) -> str:
    lines = [
        f"qa:{artifact.qa_id}",
        f"scope:{artifact.scope_mode} indices={list(artifact.selected_indices)}",
        f"answer: {artifact.answer}",
        "sources:",
    ]
    if not artifact.source_links:
        lines.append("- (none)")
    for link in artifact.source_links:
        quote_suffix = f' "{link.quote}"' if link.quote else ""
        lines.append(f"- {link.request_id}:{link.message_index}{quote_suffix}")
    return "\n".join(lines)


def estimate_qa_budget(*, question: str, selected_messages: list[dict], scope_mode: str) -> QABudgetEstimate:
    context_parts: list[str] = [question]
    for msg in selected_messages:
        role = str(msg.get("role", "unknown"))
        content = str(msg.get("content", ""))
        context_parts.append(f"[{role}] {content}")
    input_chars = len("\n".join(context_parts))
    estimated_input_tokens = max(1, math.ceil(input_chars / 4))
    estimated_output_tokens = max(96, min(512, math.ceil(len(question) / 2) + 96))
    return QABudgetEstimate(
        scope_mode=scope_mode,
        message_count=len(selected_messages),
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        estimated_total_tokens=estimated_input_tokens + estimated_output_tokens,
    )


def _parse_source_links(raw_links: object, *, request_id: str) -> list[QASourceLink]:
    if not isinstance(raw_links, list):
        return []
    parsed: list[QASourceLink] = []
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            continue
        try:
            message_index = int(raw_link.get("message_index", -1))
        except (TypeError, ValueError):
            continue
        if message_index < 0:
            continue
        parsed.append(
            QASourceLink(
                request_id=request_id,
                message_index=message_index,
                quote=str(raw_link.get("quote", "")).strip(),
            )
        )
    return parsed


def _make_qa_id(*, question: str, scope_mode: str, selected_indices: tuple[int, ...], answer: str) -> str:
    basis = "|".join(
        [
            question,
            scope_mode,
            ",".join(str(idx) for idx in selected_indices),
            answer,
        ]
    )
    return "qa_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
