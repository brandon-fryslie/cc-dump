"""Checkpoint diffing over HAR entries with behavior-focused metrics.

# [LAW:one-source-of-truth] This module is the canonical HAR checkpoint diff implementation.
# [LAW:verifiable-goals] Diff output is deterministic and machine-checkable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import shlex
from typing import Any


@dataclass(frozen=True)
class UsageMetrics:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int

    @property
    def cache_hit_ratio(self) -> float:
        total_input = self.input_tokens + self.cache_read_input_tokens
        return 0.0 if total_input == 0 else (self.cache_read_input_tokens / total_input)


@dataclass(frozen=True)
class MessageSnapshot:
    role: str
    text: str
    tool_names: tuple[str, ...]
    bash_commands: tuple[str, ...]


@dataclass(frozen=True)
class CheckpointSnapshot:
    entry_index: int
    started_at: str
    session_id: str
    model: str
    message_count: int
    messages: tuple[MessageSnapshot, ...]
    tool_counts: dict[str, int]
    usage: UsageMetrics


@dataclass(frozen=True)
class CheckpointDiff:
    before_index: int
    after_index: int
    session_id: str
    comparison_mode: str
    lcp_messages: int
    dropped_messages_from_before: int
    appended_messages: int
    appended_user_messages: tuple[str, ...]
    appended_assistant_messages: tuple[str, ...]
    appended_commands: tuple[str, ...]
    appended_command_families: dict[str, int]
    repeated_commands: dict[str, int]
    appended_tool_counts: dict[str, int]
    before_usage: UsageMetrics
    after_usage: UsageMetrics
    insights: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "before_index": self.before_index,
            "after_index": self.after_index,
            "session_id": self.session_id,
            "comparison_mode": self.comparison_mode,
            "lcp_messages": self.lcp_messages,
            "dropped_messages_from_before": self.dropped_messages_from_before,
            "appended_messages": self.appended_messages,
            "appended_user_messages": list(self.appended_user_messages),
            "appended_assistant_messages": list(self.appended_assistant_messages),
            "appended_commands": list(self.appended_commands),
            "appended_command_families": dict(self.appended_command_families),
            "repeated_commands": dict(self.repeated_commands),
            "appended_tool_counts": dict(self.appended_tool_counts),
            "before_usage": {
                "input_tokens": self.before_usage.input_tokens,
                "output_tokens": self.before_usage.output_tokens,
                "cache_creation_input_tokens": self.before_usage.cache_creation_input_tokens,
                "cache_read_input_tokens": self.before_usage.cache_read_input_tokens,
                "cache_hit_ratio": round(self.before_usage.cache_hit_ratio, 4),
            },
            "after_usage": {
                "input_tokens": self.after_usage.input_tokens,
                "output_tokens": self.after_usage.output_tokens,
                "cache_creation_input_tokens": self.after_usage.cache_creation_input_tokens,
                "cache_read_input_tokens": self.after_usage.cache_read_input_tokens,
                "cache_hit_ratio": round(self.after_usage.cache_hit_ratio, 4),
            },
            "insights": list(self.insights),
        }


def load_har_entries(har_path: Path) -> list[dict[str, Any]]:
    data = json.loads(har_path.read_text(encoding="utf-8"))
    return list(data.get("log", {}).get("entries", []))


def snapshot_from_har_entry(entry: dict[str, Any], entry_index: int) -> CheckpointSnapshot:
    request_payload = json.loads(entry["request"]["postData"]["text"])
    response_payload = json.loads(entry["response"]["content"]["text"])
    messages_payload = list(request_payload.get("messages", []))
    messages = tuple(_snapshot_message(message) for message in messages_payload)
    tool_counts = Counter()
    for message in messages:
        tool_counts.update(message.tool_names)
    return CheckpointSnapshot(
        entry_index=entry_index,
        started_at=str(entry.get("startedDateTime", "")),
        session_id=_extract_session_id(request_payload),
        model=str(request_payload.get("model", "")),
        message_count=len(messages_payload),
        messages=messages,
        tool_counts=dict(sorted(tool_counts.items())),
        usage=_extract_usage(response_payload),
    )


def diff_checkpoints(before: CheckpointSnapshot, after: CheckpointSnapshot) -> CheckpointDiff:
    if before.session_id != after.session_id:
        raise ValueError(
            "checkpoint diff requires same session_id "
            f"(before={before.session_id!r}, after={after.session_id!r})"
        )
    lcp_messages = _longest_common_prefix(before.messages, after.messages)
    appended = after.messages[lcp_messages:]
    dropped_messages = max(0, before.message_count - lcp_messages)
    comparison_mode = "append_only" if dropped_messages == 0 else "divergent"
    appended_user_messages = tuple(
        message.text for message in appended if message.role == "user" and message.text
    )
    appended_assistant_messages = tuple(
        message.text for message in appended if message.role == "assistant" and message.text
    )
    appended_commands = tuple(
        command for message in appended for command in message.bash_commands if command
    )
    appended_tool_counts = Counter(
        tool_name for message in appended for tool_name in message.tool_names if tool_name
    )
    appended_command_families = Counter(_command_family(command) for command in appended_commands)
    repeated_commands = Counter(command for command in appended_commands if command)
    repeated_commands = Counter({cmd: count for cmd, count in repeated_commands.items() if count > 1})
    insights = _derive_insights(
        comparison_mode=comparison_mode,
        dropped_messages=dropped_messages,
        appended_user_messages=appended_user_messages,
        appended_assistant_messages=appended_assistant_messages,
        repeated_commands=repeated_commands,
        command_families=appended_command_families,
        appended_tool_counts=appended_tool_counts,
        before_usage=before.usage,
        after_usage=after.usage,
    )
    return CheckpointDiff(
        before_index=before.entry_index,
        after_index=after.entry_index,
        session_id=before.session_id,
        comparison_mode=comparison_mode,
        lcp_messages=lcp_messages,
        dropped_messages_from_before=dropped_messages,
        appended_messages=len(appended),
        appended_user_messages=appended_user_messages,
        appended_assistant_messages=appended_assistant_messages,
        appended_commands=appended_commands,
        appended_command_families=dict(sorted(appended_command_families.items())),
        repeated_commands=dict(sorted(repeated_commands.items())),
        appended_tool_counts=dict(sorted(appended_tool_counts.items())),
        before_usage=before.usage,
        after_usage=after.usage,
        insights=tuple(insights),
    )


def render_diff_markdown(diff: CheckpointDiff) -> str:
    lines = [
        f"# Checkpoint Diff {diff.before_index} -> {diff.after_index}",
        "",
        f"- session: `{diff.session_id}`",
        f"- comparison mode: `{diff.comparison_mode}`",
        f"- shared message prefix: `{diff.lcp_messages}`",
        f"- dropped messages from A: `{diff.dropped_messages_from_before}`",
        f"- appended messages: `{diff.appended_messages}`",
        "",
        "## Appended User Directives",
    ]
    lines.extend(_render_bullets(diff.appended_user_messages, "(none)"))
    lines.extend(["", "## Appended Assistant Strategy Notes"])
    lines.extend(_render_bullets(diff.appended_assistant_messages, "(none)"))
    lines.extend(["", "## Appended Command Families"])
    lines.extend(_render_bullets(_kv_lines(diff.appended_command_families), "(none)"))
    lines.extend(["", "## Repeated Commands (Loop Signal)"])
    lines.extend(_render_bullets(_kv_lines(diff.repeated_commands), "(none)"))
    lines.extend(["", "## Appended Tool Counts (Delta Segment)"])
    lines.extend(_render_bullets(_kv_lines(diff.appended_tool_counts), "(none)"))
    lines.extend(
        [
            "",
            "## Cache/Token Snapshot",
            (
                f"- before usage: input={diff.before_usage.input_tokens} "
                f"cache_read={diff.before_usage.cache_read_input_tokens} "
                f"output={diff.before_usage.output_tokens} "
                f"cache_hit_ratio={diff.before_usage.cache_hit_ratio:.2f}"
            ),
            (
                f"- after usage: input={diff.after_usage.input_tokens} "
                f"cache_read={diff.after_usage.cache_read_input_tokens} "
                f"output={diff.after_usage.output_tokens} "
                f"cache_hit_ratio={diff.after_usage.cache_hit_ratio:.2f}"
            ),
            "",
            "## Insights",
        ]
    )
    lines.extend(_render_bullets(diff.insights, "(no strong signal)"))
    return "\n".join(lines)


def find_interesting_pairs(
    snapshots: list[CheckpointSnapshot],
    *,
    limit: int = 3,
) -> list[CheckpointDiff]:
    candidates: list[tuple[int, CheckpointDiff]] = []
    for i, before in enumerate(snapshots):
        for after in snapshots[i + 1 :]:
            if before.session_id != after.session_id:
                continue
            diff = diff_checkpoints(before, after)
            if diff.lcp_messages == 0:
                continue
            if diff.appended_messages < 2 or diff.appended_messages > 80:
                continue
            score = _score_diff(diff)
            if score > 0:
                candidates.append((score, diff))
    candidates.sort(key=lambda item: (-item[0], item[1].before_index, item[1].after_index))
    selected: list[CheckpointDiff] = []
    used_after: set[int] = set()
    used_fingerprints: set[tuple[Any, ...]] = set()
    for _, diff in candidates:
        if diff.after_index in used_after:
            continue
        fingerprint = (
            diff.comparison_mode,
            tuple(sorted(diff.appended_command_families.items())),
            tuple(sorted(diff.appended_tool_counts.items())),
            len(diff.appended_user_messages),
        )
        if fingerprint in used_fingerprints:
            continue
        selected.append(diff)
        used_after.add(diff.after_index)
        used_fingerprints.add(fingerprint)
        if len(selected) >= limit:
            break
    return selected


def _extract_usage(response_payload: dict[str, Any]) -> UsageMetrics:
    usage = response_payload.get("usage", {})
    return UsageMetrics(
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
        cache_read_input_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
    )


def _extract_session_id(request_payload: dict[str, Any]) -> str:
    metadata_user_id = str(request_payload.get("metadata", {}).get("user_id", ""))
    marker = "_session_"
    if marker not in metadata_user_id:
        return ""
    return metadata_user_id.split(marker, 1)[1]


def _snapshot_message(message: dict[str, Any]) -> MessageSnapshot:
    role = str(message.get("role", ""))
    content = message.get("content")
    if isinstance(content, str):
        return MessageSnapshot(role=role, text=content.strip(), tool_names=(), bash_commands=())
    if not isinstance(content, list):
        return MessageSnapshot(role=role, text="", tool_names=(), bash_commands=())
    text_parts: list[str] = []
    tool_names: list[str] = []
    bash_commands: list[str] = []
    for block in content:
        if isinstance(block, str):
            text_parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type", ""))
        if btype == "text":
            text_parts.append(str(block.get("text", "")))
            continue
        if btype != "tool_use":
            continue
        tool_name = str(block.get("name", ""))
        if tool_name:
            tool_names.append(tool_name)
        if tool_name == "Bash":
            command = str(block.get("input", {}).get("command", "")).strip()
            if command:
                bash_commands.append(command)
    return MessageSnapshot(
        role=role,
        text=" ".join(part.strip() for part in text_parts if part.strip()),
        tool_names=tuple(tool_names),
        bash_commands=tuple(bash_commands),
    )


def _longest_common_prefix(before: tuple[MessageSnapshot, ...], after: tuple[MessageSnapshot, ...]) -> int:
    limit = min(len(before), len(after))
    for idx in range(limit):
        if before[idx] != after[idx]:
            return idx
    return limit


def _counter_delta(before: Counter[str], after: Counter[str]) -> Counter[str]:
    keys = sorted(set(before) | set(after))
    delta: Counter[str] = Counter()
    for key in keys:
        diff = after.get(key, 0) - before.get(key, 0)
        if diff != 0:
            delta[key] = diff
    return delta


def _derive_insights(
    *,
    comparison_mode: str,
    dropped_messages: int,
    appended_user_messages: tuple[str, ...],
    appended_assistant_messages: tuple[str, ...],
    repeated_commands: Counter[str],
    command_families: Counter[str],
    appended_tool_counts: Counter[str],
    before_usage: UsageMetrics,
    after_usage: UsageMetrics,
) -> list[str]:
    insights: list[str] = []
    if comparison_mode == "divergent":
        insights.append(
            "Checkpoint B diverged from A (history rewritten or forked): "
            f"{dropped_messages} messages from A are not in B's prefix."
        )
    directive_count = len([text for text in appended_user_messages if text.strip()])
    if directive_count > 0:
        insights.append(f"{directive_count} new user directives landed between checkpoints.")
    if repeated_commands:
        loop_count = sum(repeated_commands.values())
        insights.append(
            f"Detected retry loop signal: {loop_count} repeated Bash invocations across "
            f"{len(repeated_commands)} unique commands."
        )
    if command_families:
        dominant_family, dominant_count = command_families.most_common(1)[0]
        insights.append(f"Dominant command family in delta: {dominant_family} ({dominant_count} calls).")
    edit_count = appended_tool_counts.get("Edit", 0)
    bash_count = appended_tool_counts.get("Bash", 0)
    if edit_count > 0 and bash_count > 0:
        insights.append(f"Mixed edit/execute cycle in delta (Edit {edit_count}, Bash {bash_count}).")
    if after_usage.cache_hit_ratio > before_usage.cache_hit_ratio:
        insights.append(
            "Cache hit ratio improved at checkpoint B, indicating better prefix reuse for this turn."
        )
    if len(appended_assistant_messages) >= 3:
        insights.append("Assistant strategy shifted multiple times (>=3 narrative strategy notes).")
    return insights


def _score_diff(diff: CheckpointDiff) -> int:
    score = (
        len(diff.appended_user_messages) * 8
        + len(diff.repeated_commands) * 6
        + sum(count for count in diff.appended_command_families.values())
        + sum(abs(delta) for delta in diff.appended_tool_counts.values())
    )
    score += 10 if diff.comparison_mode == "divergent" else 0
    score -= max(0, diff.appended_messages - 40) // 2
    return score


def _render_bullets(items: tuple[str, ...] | list[str], empty: str) -> list[str]:
    if not items:
        return [f"- {empty}"]
    return [f"- {item}" for item in items]


def _kv_lines(mapping: dict[str, int]) -> list[str]:
    return [f"{key}: {value}" for key, value in mapping.items()]


def _command_family(command: str) -> str:
    command = command.strip()
    if not command:
        return "(empty)"
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command.split(" ", 1)[0]
    if not tokens:
        return "(empty)"
    if len(tokens) >= 3 and tokens[0] == "uv" and tokens[1] == "run":
        return f"{tokens[0]} {tokens[1]} {tokens[2]}"
    if len(tokens) >= 2:
        return f"{tokens[0]} {tokens[1]}"
    return tokens[0]
