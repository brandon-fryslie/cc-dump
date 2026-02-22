"""Registered lightweight AI utility catalog with lifecycle policy metadata.

// [LAW:no-mode-explosion] Utility set is bounded and centrally registered.
// [LAW:one-source-of-truth] Utility metadata and fallback behavior live in one registry.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class UtilitySpec:
    utility_id: str
    title: str
    instruction: str
    owner: str
    budget_cap_tokens: int
    success_metric: str
    removal_criteria: str
    fallback_behavior: str
    version: str = "v1"


_UTILITY_SPECS: tuple[UtilitySpec, ...] = (
    UtilitySpec(
        utility_id="turn_title",
        title="Turn Title",
        instruction="Generate a concise 4-7 word title for the selected conversation context.",
        owner="side-channel",
        budget_cap_tokens=300,
        success_metric="title is concise and reflects primary intent",
        removal_criteria="remove if users stop using title suggestions or titles are consistently noisy",
        fallback_behavior="derive title from first significant words in selected context",
    ),
    UtilitySpec(
        utility_id="glossary_extract",
        title="Glossary Extract",
        instruction="Extract key acronyms and domain terms with one-line definitions.",
        owner="side-channel",
        budget_cap_tokens=400,
        success_metric="terms are relevant and definitions are useful",
        removal_criteria="remove if extracted terms are mostly duplicates or irrelevant",
        fallback_behavior="extract uppercase/acronym-like tokens without definitions",
    ),
    UtilitySpec(
        utility_id="recent_changes_digest",
        title="Recent Changes Digest",
        instruction="Summarize what changed in the selected context as 3 concise bullets.",
        owner="side-channel",
        budget_cap_tokens=450,
        success_metric="digest captures changes without omitting major updates",
        removal_criteria="remove if digest quality is lower than standard summary output",
        fallback_behavior="emit message-count/role-count digest",
    ),
    UtilitySpec(
        utility_id="intent_tags",
        title="Intent Tags",
        instruction="Classify selected context into 3-5 intent/topic tags.",
        owner="side-channel",
        budget_cap_tokens=300,
        success_metric="tags align with user intent and aid filtering/search",
        removal_criteria="remove if tags do not improve downstream navigation",
        fallback_behavior="keyword-based coarse tags",
    ),
    UtilitySpec(
        utility_id="search_query_terms",
        title="Search Query Terms",
        instruction="Suggest 5 high-signal search query terms for the selected context.",
        owner="side-channel",
        budget_cap_tokens=300,
        success_metric="suggestions improve hit quality in conversation search",
        removal_criteria="remove if suggestions do not improve retrieval quality",
        fallback_behavior="extract frequent non-trivial tokens from selected context",
    ),
)


class UtilityRegistry:
    """Canonical registry for lightweight utility definitions."""

    def list(self) -> list[UtilitySpec]:
        return list(_UTILITY_SPECS)

    def get(self, utility_id: str) -> UtilitySpec | None:
        for spec in _UTILITY_SPECS:
            if spec.utility_id == utility_id:
                return spec
        return None


def fallback_utility_output(utility_id: str, messages: list[dict]) -> str:
    """Deterministic fallback output per utility."""
    context = _messages_to_text(messages)
    if utility_id == "turn_title":
        words = [w for w in re.findall(r"[A-Za-z0-9_]+", context) if len(w) > 2]
        return " ".join(words[:7]) if words else "Untitled context"
    if utility_id == "glossary_extract":
        acronyms = sorted({w for w in re.findall(r"\b[A-Z][A-Z0-9_]{1,}\b", context)})[:10]
        return "\n".join(f"- {token}" for token in acronyms) if acronyms else "- (no glossary terms found)"
    if utility_id == "recent_changes_digest":
        role_counts: dict[str, int] = {}
        for msg in messages:
            role = str(msg.get("role", "unknown"))
            role_counts[role] = role_counts.get(role, 0) + 1
        parts = [f"{count} {role}" for role, count in sorted(role_counts.items())]
        return f"{len(messages)} messages ({', '.join(parts)})"
    if utility_id == "intent_tags":
        lowered = context.lower()
        tags: list[str] = []
        tags.extend(["debug"] if "error" in lowered or "bug" in lowered else [])
        tags.extend(["planning"] if "plan" in lowered or "roadmap" in lowered else [])
        tags.extend(["implementation"] if "implement" in lowered or "code" in lowered else [])
        tags.extend(["testing"] if "test" in lowered else [])
        deduped = sorted(set(tags))
        return ", ".join(deduped) if deduped else "general"
    if utility_id == "search_query_terms":
        tokens = [
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_]+", context)
            if len(token) > 4
        ]
        unique: list[str] = []
        for token in tokens:
            if token in unique:
                continue
            unique.append(token)
            if len(unique) == 8:
                break
        return ", ".join(unique) if unique else "conversation, summary"
    return "(unknown utility fallback)"


def utility_prompt(spec: UtilitySpec, context: str) -> str:
    if not context:
        return spec.instruction
    return f"{spec.instruction}\n\n{context}"


def _messages_to_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role", "unknown"))
        content = message.get("content", "")
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)
