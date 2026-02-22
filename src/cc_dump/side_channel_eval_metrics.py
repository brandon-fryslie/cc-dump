"""Canonical machine-verifiable acceptance thresholds for side-channel purposes.

// [LAW:one-source-of-truth] Gate thresholds are centralized here for local and CI use.
"""

from __future__ import annotations


PURPOSE_MIN_PASS_RATE: dict[str, float] = {
    "block_summary": 1.0,
    "decision_ledger": 1.0,
    "checkpoint_summary": 1.0,
    "action_extraction": 1.0,
    "handoff_note": 1.0,
    "incident_timeline": 1.0,
    "conversation_qa": 1.0,
    "segregation": 1.0,
    "budget_guardrails": 1.0,
}
