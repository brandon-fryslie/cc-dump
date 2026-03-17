"""Tests for FenwickTree and MaxTracker data structures."""

from __future__ import annotations

import random

import pytest

from cc_dump.tui.prefix_sum_tree import FenwickTree, MaxTracker


# ─── FenwickTree ──────────────────────────────────────────────────────


class TestFenwickTreeEmpty:
    def test_empty_tree_has_zero_total(self):
        t = FenwickTree()
        assert t.total() == 0
        assert len(t) == 0
        assert t.size == 0

    def test_empty_tree_find_returns_none(self):
        t = FenwickTree()
        assert t.find(0) is None
        assert t.find(1) is None
        assert t.find(-1) is None

    def test_empty_tree_prefix_sum_zero(self):
        t = FenwickTree()
        assert t.prefix_sum(0) == 0


class TestFenwickTreeSingle:
    def test_single_element(self):
        t = FenwickTree()
        t.append(5)
        assert len(t) == 1
        assert t.get(0) == 5
        assert t.total() == 5
        assert t.prefix_sum(0) == 0
        assert t.prefix_sum(1) == 5

    def test_single_element_find(self):
        t = FenwickTree()
        t.append(5)
        assert t.find(0) == (0, 0)
        assert t.find(4) == (0, 0)
        assert t.find(5) is None  # beyond total

    def test_single_zero_height(self):
        t = FenwickTree()
        t.append(0)
        assert t.find(0) is None  # zero-height turn contains nothing


class TestFenwickTreeMultiple:
    @pytest.fixture()
    def tree(self):
        t = FenwickTree()
        for v in [3, 2, 5, 1]:
            t.append(v)
        return t

    def test_prefix_sums(self, tree):
        assert tree.prefix_sum(0) == 0
        assert tree.prefix_sum(1) == 3
        assert tree.prefix_sum(2) == 5
        assert tree.prefix_sum(3) == 10
        assert tree.prefix_sum(4) == 11

    def test_get_values(self, tree):
        assert tree.get(0) == 3
        assert tree.get(1) == 2
        assert tree.get(2) == 5
        assert tree.get(3) == 1

    def test_total(self, tree):
        assert tree.total() == 11

    def test_find_first_turn(self, tree):
        assert tree.find(0) == (0, 0)
        assert tree.find(1) == (0, 0)
        assert tree.find(2) == (0, 0)

    def test_find_second_turn(self, tree):
        assert tree.find(3) == (1, 3)
        assert tree.find(4) == (1, 3)

    def test_find_third_turn(self, tree):
        assert tree.find(5) == (2, 5)
        assert tree.find(9) == (2, 5)

    def test_find_fourth_turn(self, tree):
        assert tree.find(10) == (3, 10)

    def test_find_beyond_total(self, tree):
        assert tree.find(11) is None
        assert tree.find(100) is None

    def test_find_negative(self, tree):
        assert tree.find(-1) is None


class TestFenwickTreePointUpdate:
    def test_update_increases_element(self):
        t = FenwickTree()
        for v in [3, 2, 5]:
            t.append(v)
        t.update(1, 3)  # 2 → 5
        assert t.get(1) == 5
        assert t.prefix_sum(2) == 8  # 3 + 5
        assert t.total() == 13  # 3 + 5 + 5

    def test_update_decreases_element(self):
        t = FenwickTree()
        for v in [3, 2, 5]:
            t.append(v)
        t.update(2, -3)  # 5 → 2
        assert t.get(2) == 2
        assert t.total() == 7

    def test_set_value(self):
        t = FenwickTree()
        for v in [3, 2, 5]:
            t.append(v)
        t.set(1, 10)
        assert t.get(1) == 10
        assert t.total() == 18  # 3 + 10 + 5

    def test_set_same_value_is_noop(self):
        t = FenwickTree()
        for v in [3, 2, 5]:
            t.append(v)
        t.set(1, 2)  # no change
        assert t.get(1) == 2
        assert t.total() == 10

    def test_find_after_update(self):
        t = FenwickTree()
        for v in [3, 2, 5, 1]:
            t.append(v)
        # Increase turn 0 from 3 to 10
        t.set(0, 10)
        assert t.find(0) == (0, 0)
        assert t.find(9) == (0, 0)
        assert t.find(10) == (1, 10)  # turn 1 now starts at 10
        assert t.find(12) == (2, 12)  # turn 2 now starts at 12


class TestFenwickTreeZeroHeightTurns:
    def test_zero_height_skipped_in_find(self):
        t = FenwickTree()
        for v in [3, 0, 5]:
            t.append(v)
        # Line 3 should be in turn 2 (turn 1 has 0 height)
        assert t.find(3) == (2, 3)
        assert t.find(2) == (0, 0)

    def test_consecutive_zeros(self):
        t = FenwickTree()
        for v in [3, 0, 0, 5]:
            t.append(v)
        assert t.find(3) == (3, 3)
        assert t.find(2) == (0, 0)

    def test_leading_zeros(self):
        t = FenwickTree()
        for v in [0, 0, 5]:
            t.append(v)
        assert t.find(0) == (2, 0)
        assert t.find(4) == (2, 0)
        assert t.find(5) is None

    def test_all_zeros(self):
        t = FenwickTree()
        for v in [0, 0, 0]:
            t.append(v)
        assert t.find(0) is None


class TestFenwickTreeBoundary:
    def test_find_exact_boundary_between_turns(self):
        """Line at exact boundary falls into the next turn."""
        t = FenwickTree()
        for v in [3, 2]:
            t.append(v)
        assert t.find(2) == (0, 0)   # last line of turn 0
        assert t.find(3) == (1, 3)   # first line of turn 1

    def test_single_line_turns(self):
        t = FenwickTree()
        for v in [1, 1, 1]:
            t.append(v)
        assert t.find(0) == (0, 0)
        assert t.find(1) == (1, 1)
        assert t.find(2) == (2, 2)
        assert t.find(3) is None


class TestFenwickTreeRebuild:
    def test_rebuild_matches_incremental(self):
        values = [3, 2, 5, 1, 4, 7, 2]
        # Build incrementally
        t1 = FenwickTree()
        for v in values:
            t1.append(v)
        # Build via rebuild
        t2 = FenwickTree()
        t2.rebuild(values)
        # All prefix sums match
        for i in range(len(values) + 1):
            assert t1.prefix_sum(i) == t2.prefix_sum(i)

    def test_rebuild_replaces_existing(self):
        t = FenwickTree()
        for v in [100, 200]:
            t.append(v)
        t.rebuild([1, 2, 3])
        assert len(t) == 3
        assert t.total() == 6

    def test_clear(self):
        t = FenwickTree()
        for v in [3, 2, 5]:
            t.append(v)
        t.clear()
        assert len(t) == 0
        assert t.total() == 0
        assert t.find(0) is None


class TestFenwickTreeLarge:
    def test_large_tree_correctness(self):
        """Verify prefix sums against naive computation for 10K elements."""
        rng = random.Random(42)
        values = [rng.randint(0, 100) for _ in range(10_000)]
        t = FenwickTree()
        t.rebuild(values)

        # Spot-check prefix sums
        naive_prefix = 0
        for i in range(len(values)):
            assert t.prefix_sum(i) == naive_prefix
            naive_prefix += values[i]
        assert t.total() == sum(values)

    def test_incremental_updates_match_rebuild(self):
        """Modify random elements and verify prefix sums still match."""
        rng = random.Random(99)
        values = [rng.randint(1, 50) for _ in range(1_000)]
        t = FenwickTree()
        t.rebuild(values)

        for _ in range(200):
            idx = rng.randint(0, len(values) - 1)
            new_val = rng.randint(0, 50)
            values[idx] = new_val
            t.set(idx, new_val)

        naive_prefix = 0
        for i in range(len(values)):
            assert t.prefix_sum(i) == naive_prefix
            naive_prefix += values[i]

    def test_find_large_tree(self):
        """Verify find against naive search for 5K elements."""
        rng = random.Random(77)
        values = [rng.randint(1, 20) for _ in range(5_000)]
        t = FenwickTree()
        t.rebuild(values)

        offsets = []
        running = 0
        for v in values:
            offsets.append(running)
            running += v

        # Spot-check 100 random targets
        for _ in range(100):
            target = rng.randint(0, sum(values) - 1)
            result = t.find(target)
            assert result is not None
            idx, offset = result
            assert offset == offsets[idx]
            assert offset <= target < offset + values[idx]


class TestFenwickTreeAppendSequence:
    def test_append_sequence_matches_rebuild(self):
        values = [7, 0, 3, 0, 0, 12, 1, 5, 0, 2]
        t_append = FenwickTree()
        for v in values:
            t_append.append(v)
        t_rebuild = FenwickTree()
        t_rebuild.rebuild(values)
        for i in range(len(values) + 1):
            assert t_append.prefix_sum(i) == t_rebuild.prefix_sum(i)

    def test_append_after_rebuild(self):
        t = FenwickTree()
        t.rebuild([3, 2])
        t.append(5)
        assert len(t) == 3
        assert t.total() == 10
        assert t.get(2) == 5
        assert t.prefix_sum(2) == 5


# ─── MaxTracker ───────────────────────────────────────────────────────


class TestMaxTrackerEmpty:
    def test_empty_max_is_zero(self):
        m = MaxTracker()
        assert m.max == 0

    def test_clear_resets(self):
        m = MaxTracker()
        m.add(10)
        m.clear()
        assert m.max == 0


class TestMaxTrackerBasic:
    def test_add_single(self):
        m = MaxTracker()
        m.add(5)
        assert m.max == 5

    def test_add_multiple_increasing(self):
        m = MaxTracker()
        m.add(1)
        m.add(5)
        m.add(3)
        assert m.max == 5

    def test_add_duplicate_max(self):
        m = MaxTracker()
        m.add(5)
        m.add(5)
        assert m.max == 5


class TestMaxTrackerRemove:
    def test_remove_non_max(self):
        m = MaxTracker()
        m.add(5)
        m.add(3)
        m.remove(3)
        assert m.max == 5

    def test_remove_max_with_duplicate(self):
        m = MaxTracker()
        m.add(5)
        m.add(5)
        m.add(3)
        m.remove(5)
        assert m.max == 5  # still one 5 remaining

    def test_remove_last_max(self):
        m = MaxTracker()
        m.add(5)
        m.add(3)
        m.add(1)
        m.remove(5)
        assert m.max == 3

    def test_remove_only_element(self):
        m = MaxTracker()
        m.add(5)
        m.remove(5)
        assert m.max == 0

    def test_remove_nonexistent_is_noop(self):
        m = MaxTracker()
        m.add(5)
        m.remove(99)
        assert m.max == 5


class TestMaxTrackerReplace:
    def test_replace_non_max_with_larger(self):
        m = MaxTracker()
        m.add(5)
        m.add(3)
        m.replace(3, 10)
        assert m.max == 10

    def test_replace_max_with_smaller(self):
        m = MaxTracker()
        m.add(5)
        m.add(3)
        m.replace(5, 1)
        assert m.max == 3

    def test_replace_same_value_is_noop(self):
        m = MaxTracker()
        m.add(5)
        m.replace(5, 5)
        assert m.max == 5


class TestMaxTrackerRebuild:
    def test_rebuild_from_list(self):
        m = MaxTracker()
        m.rebuild([3, 7, 2, 5])
        assert m.max == 7

    def test_rebuild_replaces_existing(self):
        m = MaxTracker()
        m.add(100)
        m.rebuild([1, 2, 3])
        assert m.max == 3

    def test_rebuild_empty(self):
        m = MaxTracker()
        m.add(10)
        m.rebuild([])
        assert m.max == 0
