"""Optional beads issue bridge for accepted action items.

// [LAW:locality-or-seam] beads CLI integration is isolated behind one adapter.
// [LAW:single-enforcer] This module is the single creator for default beads links.
"""

from __future__ import annotations

import re
import subprocess

from cc_dump.ai.action_items import ActionWorkItem


_ISSUE_ID_PATTERN = re.compile(r"\b([a-z0-9-]+-[a-z0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)


def create_beads_issue_for_item(item: ActionWorkItem) -> str:
    """Create beads task for an accepted item and return created issue id."""
    title_prefix = "Deferred:" if item.kind == "deferred" else "Action:"
    title = f"{title_prefix} {item.text}"
    description_lines = [
        f"Source kind: {item.kind}",
        f"Confidence: {item.confidence:.2f}",
        f"Owner hint: {item.owner or '(none)'}",
        f"Due hint: {item.due_hint or '(none)'}",
        f"Source links: {', '.join(_render_source_links(item)) or '(none)'}",
    ]
    cmd = [
        "bd",
        "create",
        title,
        "--type",
        "task",
        "--priority",
        "2",
        "--labels",
        "action-items,side-channel",
        "--description",
        "\n".join(description_lines),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    output = f"{result.stdout}\n{result.stderr}"
    match = _ISSUE_ID_PATTERN.search(output)
    return match.group(1) if match is not None else ""


def _render_source_links(item: ActionWorkItem) -> list[str]:
    return [
        f"{link.request_id}:{link.message_index}"
        for link in item.source_links
    ]
