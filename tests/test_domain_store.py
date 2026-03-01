"""Tests for DomainStore retention and lifecycle."""

from cc_dump.app.domain_store import DomainStore


def test_completed_turn_retention_prunes_oldest_and_notifies():
    pruned: list[int] = []
    ds = DomainStore(max_completed_turns=2)
    ds.on_turns_pruned = lambda count: pruned.append(count)

    ds.add_turn(["t1"])
    ds.add_turn(["t2"])
    ds.add_turn(["t3"])

    assert ds.iter_completed_blocks() == [["t2"], ["t3"]]
    assert pruned == [1]
