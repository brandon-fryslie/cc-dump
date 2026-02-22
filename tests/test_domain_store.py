"""Tests for DomainStore attribution helpers."""

from types import SimpleNamespace

from cc_dump.domain_store import DomainStore


def test_get_completed_lane_counts_uses_block_attribution():
    ds = DomainStore()
    ds.add_turn([SimpleNamespace(agent_kind="main")])
    ds.add_turn([SimpleNamespace(agent_kind="subagent")])
    ds.add_turn([SimpleNamespace(agent_kind="")])

    counts = ds.get_completed_lane_counts()
    assert counts["main"] == 1
    assert counts["subagent"] == 1
    assert counts["unknown"] == 1


def test_get_active_lane_counts_uses_stream_meta():
    ds = DomainStore()
    ds.begin_stream("req-main", {"agent_kind": "main"})
    ds.begin_stream("req-sub", {"agent_kind": "subagent"})
    ds.begin_stream("req-unknown", {})

    counts = ds.get_active_lane_counts()
    assert counts["main"] == 1
    assert counts["subagent"] == 1
    assert counts["unknown"] == 1
