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


def test_recent_stream_chips_persist_until_next_stream_start():
    ds = DomainStore()
    ds.begin_stream("req-main", {"agent_kind": "main", "agent_label": "main"})

    active = ds.get_active_stream_chips()
    assert active == (("req-main", "main", "main"),)

    ds.finalize_stream_with_blocks("req-main", [])
    after_finalize = ds.get_active_stream_chips()
    assert after_finalize == (("req-main", "main \u2713", "main"),)

    # Starting a new stream clears prior completed chips.
    ds.begin_stream("req-sub", {"agent_kind": "subagent", "agent_label": "subagent 1"})
    after_new_stream = ds.get_active_stream_chips()
    assert after_new_stream == (("req-sub", "subagent 1", "subagent"),)


def test_completed_turn_retention_prunes_oldest_and_notifies():
    pruned: list[int] = []
    ds = DomainStore(max_completed_turns=2)
    ds.on_turns_pruned = lambda count: pruned.append(count)

    ds.add_turn(["t1"])
    ds.add_turn(["t2"])
    ds.add_turn(["t3"])

    assert ds.iter_completed_blocks() == [["t2"], ["t3"]]
    assert pruned == [1]
