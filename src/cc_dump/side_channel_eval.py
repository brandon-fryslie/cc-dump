"""Deterministic side-channel evaluation harness.

Usage:
  python -m cc_dump.side_channel_eval --check --output .artifacts/side_channel_eval.json

// [LAW:verifiable-goals] Harness emits machine-checkable pass/fail metrics.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from cc_dump.action_items import ActionItemStore, parse_action_items
from cc_dump.checkpoints import render_checkpoint_diff
from cc_dump.conversation_qa import QAScope, normalize_scope, parse_qa_artifact
from cc_dump.data_dispatcher import DataDispatcher
from cc_dump.decision_ledger import parse_decision_entries
from cc_dump.handoff_notes import SECTION_ORDER, parse_handoff_artifact, render_handoff_markdown
from cc_dump.incident_timeline import parse_incident_timeline_artifact, render_incident_timeline_markdown
from cc_dump.side_channel import SideChannelManager
from cc_dump.side_channel_eval_metrics import PURPOSE_MIN_PASS_RATE
from cc_dump.side_channel_marker import extract_marker, strip_marker_from_body


_DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "side-channel"
    / "eval"
    / "side_channel_eval_corpus.json"
)


@dataclass(frozen=True)
class EvalCheck:
    purpose: str
    check: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "check": self.check,
            "passed": self.passed,
            "detail": self.detail,
        }


def run_evaluation(corpus_path: Path) -> dict[str, Any]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    checks = _collect_checks(corpus)
    return _build_report(checks)


def _collect_checks(corpus: dict[str, Any]) -> list[EvalCheck]:
    checks: list[EvalCheck] = []
    checks.extend(_evaluate_block_summary(corpus))
    checks.extend(_evaluate_decision_ledger(corpus))
    checks.extend(_evaluate_checkpoint_summary(corpus))
    checks.extend(_evaluate_action_extraction(corpus))
    checks.extend(_evaluate_handoff_note(corpus))
    checks.extend(_evaluate_incident_timeline(corpus))
    checks.extend(_evaluate_conversation_qa(corpus))
    checks.extend(_evaluate_segregation(corpus))
    checks.extend(_evaluate_budget_guardrails())
    return checks


def _evaluate_block_summary(corpus: dict[str, Any]) -> list[EvalCheck]:
    mgr = SideChannelManager()
    mgr.enabled = False
    dispatcher = DataDispatcher(mgr)
    messages = list(corpus["block_summary"]["messages"])
    result = dispatcher.summarize_messages(messages)
    return [
        EvalCheck(
            purpose="block_summary",
            check="fallback_summary_nonempty",
            passed=result.source == "fallback" and bool(result.text.strip()),
            detail=result.text[:120],
        ),
    ]


def _evaluate_decision_ledger(corpus: dict[str, Any]) -> list[EvalCheck]:
    item = corpus["decision_ledger"]
    entries = parse_decision_entries(item["text"], request_id=item["request_id"])
    passed = (
        len(entries) == 1
        and entries[0].decision_id == "dec_scope"
        and entries[0].source_links
        and entries[0].source_links[0].request_id == item["request_id"]
    )
    return [EvalCheck("decision_ledger", "structured_parse_with_sources", passed)]


def _evaluate_checkpoint_summary(corpus: dict[str, Any]) -> list[EvalCheck]:
    mgr = SideChannelManager()
    mgr.enabled = False
    dispatcher = DataDispatcher(mgr)
    messages = list(corpus["checkpoint_summary"]["messages"])
    first = dispatcher.create_checkpoint(messages, source_start=0, source_end=0, request_id="req-c1")
    second = dispatcher.create_checkpoint(messages, source_start=0, source_end=1, request_id="req-c2")
    diff_text = render_checkpoint_diff(before=first.artifact, after=second.artifact)
    return [
        EvalCheck(
            "checkpoint_summary",
            "range_linked_artifact",
            passed=first.artifact.source_start == 0 and second.artifact.source_end == 1,
        ),
        EvalCheck(
            "checkpoint_summary",
            "deterministic_diff_contains_links",
            passed=(
                first.artifact.checkpoint_id in diff_text
                and second.artifact.checkpoint_id in diff_text
                and "source_ranges:" in diff_text
            ),
        ),
    ]


def _evaluate_action_extraction(corpus: dict[str, Any]) -> list[EvalCheck]:
    item = corpus["action_extraction"]
    parsed = parse_action_items(item["text"], request_id=item["request_id"])
    store = ActionItemStore()
    batch_id = store.stage(parsed)
    accepted_before = len(store.accepted_snapshot())
    accepted = store.accept(batch_id=batch_id, item_ids=[parsed[0].item_id] if parsed else [])
    return [
        EvalCheck("action_extraction", "structured_parse", passed=len(parsed) == 1 and parsed[0].kind == "action"),
        EvalCheck(
            "action_extraction",
            "explicit_acceptance_required",
            passed=accepted_before == 0 and len(accepted) == 1 and accepted[0].status == "accepted",
        ),
    ]


def _evaluate_handoff_note(corpus: dict[str, Any]) -> list[EvalCheck]:
    item = corpus["handoff_note"]
    artifact = parse_handoff_artifact(
        item["text"],
        purpose="handoff_note",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id=item["request_id"],
        source_start=0,
        source_end=5,
    )
    markdown = render_handoff_markdown(artifact)
    has_all_sections = all(section_name in artifact.sections for section_name in SECTION_ORDER)
    headers_present = all(f"## {name.replace('_', ' ')}" in markdown for name in SECTION_ORDER)
    return [
        EvalCheck("handoff_note", "required_sections_present", passed=has_all_sections),
        EvalCheck("handoff_note", "required_headers_rendered", passed=headers_present),
    ]


def _evaluate_incident_timeline(corpus: dict[str, Any]) -> list[EvalCheck]:
    item = corpus["incident_timeline"]
    facts_only = parse_incident_timeline_artifact(
        item["text"],
        purpose="incident_timeline",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id=item["request_id"],
        source_start=0,
        source_end=5,
        include_hypotheses=False,
    )
    with_hyp = parse_incident_timeline_artifact(
        item["text"],
        purpose="incident_timeline",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id=item["request_id"],
        source_start=0,
        source_end=5,
        include_hypotheses=True,
    )
    rendered = render_incident_timeline_markdown(with_hyp, include_hypotheses=True)
    return [
        EvalCheck(
            "incident_timeline",
            "facts_sorted_chronologically",
            passed=(len(with_hyp.facts) >= 2 and with_hyp.facts[0].timestamp <= with_hyp.facts[1].timestamp),
        ),
        EvalCheck(
            "incident_timeline",
            "mode_toggle_controls_hypotheses",
            passed=(facts_only.hypotheses == [] and len(with_hyp.hypotheses) == 1 and "## hypotheses" in rendered),
        ),
    ]


def _evaluate_conversation_qa(corpus: dict[str, Any]) -> list[EvalCheck]:
    item = corpus["conversation_qa"]
    messages = list(item["messages"])
    mgr = SideChannelManager()
    mgr.enabled = False
    dispatcher = DataDispatcher(mgr)

    scope_check = dispatcher.ask_conversation_question(
        messages,
        question=item["question"],
        scope=QAScope(mode="whole_session", explicit_whole_session=False),
        request_id=item["request_id"],
    )
    parsed = parse_qa_artifact(
        item["text"],
        purpose="conversation_qa",
        prompt_version="v1",
        question=item["question"],
        request_id=item["request_id"],
        normalized_scope=normalize_scope(QAScope(source_start=0, source_end=1), total_messages=len(messages)),
    )
    return [
        EvalCheck(
            "conversation_qa",
            "whole_session_scope_requires_explicit_selection",
            passed=(scope_check.source == "fallback" and "Scope error" in scope_check.markdown),
        ),
        EvalCheck(
            "conversation_qa",
            "structured_answer_with_sources",
            passed=bool(parsed.answer) and len(parsed.source_links) >= 1,
        ),
        EvalCheck(
            "conversation_qa",
            "pre_send_budget_estimate_present",
            passed=scope_check.estimate.estimated_total_tokens > 0,
        ),
    ]


def _evaluate_segregation(corpus: dict[str, Any]) -> list[EvalCheck]:
    body = dict(corpus["segregation"]["body"])
    marker_present = extract_marker(body) is not None
    stripped = strip_marker_from_body(body)
    marker_removed = extract_marker(stripped) is None
    return [
        EvalCheck(
            "segregation",
            "marker_strip_transform",
            passed=marker_present and marker_removed,
        )
    ]


def _evaluate_budget_guardrails() -> list[EvalCheck]:
    mgr = SideChannelManager()
    mgr.set_budget_caps({"block_summary": 10})
    mgr.set_usage_provider(
        lambda _purpose: {
            "input_tokens": 5,
            "cache_read_tokens": 3,
            "cache_creation_tokens": 0,
            "output_tokens": 2,
        }
    )
    result = mgr.run(
        prompt="test",
        purpose="block_summary",
        profile="ephemeral_default",
    )
    return [
        EvalCheck(
            "budget_guardrails",
            "cap_blocks_request",
            passed=bool(result.error and "Guardrail:" in result.error),
        )
    ]


def _build_report(checks: list[EvalCheck]) -> dict[str, Any]:
    by_purpose: dict[str, list[EvalCheck]] = {}
    for check in checks:
        by_purpose.setdefault(check.purpose, []).append(check)

    purpose_rows: dict[str, Any] = {}
    for purpose in sorted(by_purpose):
        rows = by_purpose[purpose]
        total = len(rows)
        passed = sum(1 for row in rows if row.passed)
        pass_rate = passed / total if total else 0.0
        threshold = PURPOSE_MIN_PASS_RATE.get(purpose, 1.0)
        purpose_rows[purpose] = {
            "checks_total": total,
            "checks_passed": passed,
            "pass_rate": round(pass_rate, 4),
            "min_pass_rate": threshold,
            "status": "pass" if pass_rate >= threshold else "fail",
        }

    total_checks = len(checks)
    passed_checks = sum(1 for check in checks if check.passed)
    summary_rate = passed_checks / total_checks if total_checks else 0.0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "checks_total": total_checks,
            "checks_passed": passed_checks,
            "pass_rate": round(summary_rate, 4),
        },
        "purposes": purpose_rows,
        "checks": [
            check.to_dict()
            for check in sorted(checks, key=lambda row: (row.purpose, row.check))
        ],
    }


def _gate_failures(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for purpose, row in report.get("purposes", {}).items():
        if row.get("status") != "pass":
            failures.append(
                f"{purpose}: pass_rate={row.get('pass_rate')} threshold={row.get('min_pass_rate')}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic side-channel evaluation gates.")
    parser.add_argument(
        "--corpus",
        default=str(_DEFAULT_CORPUS_PATH),
        help="Path to fixed evaluation corpus JSON.",
    )
    parser.add_argument(
        "--output",
        default=".artifacts/side_channel_eval.json",
        help="Path to write evaluation report JSON.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when any purpose falls below threshold.",
    )
    args = parser.parse_args(argv)

    corpus_path = Path(args.corpus)
    report = run_evaluation(corpus_path)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    failures = _gate_failures(report)
    if args.check and failures:
        for failure in failures:
            print("GATE_FAIL:", failure)
        return 1
    print(f"Wrote side-channel evaluation report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
