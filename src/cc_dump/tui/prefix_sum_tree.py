"""Fenwick tree (BIT) and max tracker for O(log n) offset operations.

// [LAW:one-source-of-truth] FenwickTree IS the line-offset source of truth.
// [LAW:single-enforcer] All offset queries go through the tree.
"""

from __future__ import annotations


class FenwickTree:
    """Binary indexed tree for O(log n) prefix sum queries and point updates.

    Stores per-turn line counts. ``prefix_sum(i)`` returns the cumulative line
    count of turns ``[0, i)`` — i.e. the line offset of turn *i*.

    Internally 1-indexed; the public API uses 0-indexed positions.
    A shadow ``_values`` array keeps element values for O(1) ``get``.
    """

    __slots__ = ("_tree", "_values", "_n")

    def __init__(self, size: int = 0) -> None:
        self._n = size
        self._tree = [0] * (size + 1)  # 1-indexed
        self._values = [0] * size

    # ── Point operations ──────────────────────────────────────────────

    def update(self, i: int, delta: int) -> None:
        """Add *delta* to element at 0-indexed position *i*. O(log n)."""
        self._values[i] += delta
        i += 1  # convert to 1-indexed
        while i <= self._n:
            self._tree[i] += delta
            i += i & (-i)

    def get(self, i: int) -> int:
        """Element value at 0-indexed position *i*. O(1)."""
        return self._values[i]

    def set(self, i: int, value: int) -> None:
        """Set element at 0-indexed position *i* to *value*. O(log n)."""
        delta = value - self._values[i]
        if delta != 0:
            self.update(i, delta)

    # ── Aggregate queries ─────────────────────────────────────────────

    def prefix_sum(self, i: int) -> int:
        """Sum of elements ``[0, i)``. O(log n).

        This is the line offset of turn *i*.
        ``prefix_sum(0) == 0`` always.
        """
        s = 0
        while i > 0:
            s += self._tree[i]
            i -= i & (-i)
        return s

    def total(self) -> int:
        """Sum of all elements. O(log n)."""
        return self.prefix_sum(self._n)

    def find(self, target: int) -> tuple[int, int] | None:
        """Find the turn containing line *target*.

        Returns ``(index, offset)`` where *index* is 0-indexed and *offset*
        is ``prefix_sum(index)`` — the starting line of that turn.

        Uses the standard O(log n) walk-down technique (no binary search
        over ``prefix_sum``).  Zero-height turns are naturally skipped.

        Returns ``None`` when *target* is out of range.
        """
        if target < 0 or self._n == 0:
            return None

        pos = 0  # 1-indexed accumulator
        cumulative = 0
        bit = 1
        while bit <= self._n:
            bit <<= 1
        bit >>= 1

        while bit > 0:
            next_pos = pos + bit
            if next_pos <= self._n and cumulative + self._tree[next_pos] <= target:
                cumulative += self._tree[next_pos]
                pos = next_pos
            bit >>= 1

        # pos is now 0-indexed (walk-down produces the 0-based turn index).
        if pos >= self._n:
            return None
        # Verify the turn actually contains this line (non-zero height).
        if self._values[pos] == 0:
            return None
        return (pos, cumulative)

    # ── Structural mutations ──────────────────────────────────────────

    def append(self, value: int) -> None:
        """Grow by one element with *value*. O(log n)."""
        self._n += 1
        n = self._n
        self._values.append(value)

        # Build tree[n] from children.
        tree_val = value
        child_size = 1
        lowbit = n & (-n)
        while child_size < lowbit:
            child_pos = n - child_size
            if child_pos > 0:
                tree_val += self._tree[child_pos]
            child_size <<= 1

        if n < len(self._tree):
            self._tree[n] = tree_val
        else:
            self._tree.append(tree_val)

    def rebuild(self, values: list[int]) -> None:
        """Rebuild tree from a list of values. O(n)."""
        self._n = len(values)
        self._values = list(values)
        self._tree = [0] * (self._n + 1)
        for i, v in enumerate(values):
            self._tree[i + 1] = v
        # Standard O(n) propagation.
        for i in range(1, self._n + 1):
            j = i + (i & (-i))
            if j <= self._n:
                self._tree[j] += self._tree[i]

    def clear(self) -> None:
        """Reset to empty. O(1)."""
        self._n = 0
        self._tree = [0]
        self._values = []

    # ── Introspection ─────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return self._n

    def __len__(self) -> int:
        return self._n

    def __repr__(self) -> str:
        return f"FenwickTree(size={self._n}, total={self.total()})"


class MaxTracker:
    """Track the global maximum across a dynamic multiset of values.

    Uses a ``dict[int, int]`` (value → count) with a cached max.
    // [LAW:one-source-of-truth] This tracker IS the widest-strip truth.
    """

    __slots__ = ("_counts", "_max_value")

    def __init__(self) -> None:
        self._counts: dict[int, int] = {}
        self._max_value: int = 0

    def add(self, value: int) -> None:
        """Add a value. O(1)."""
        self._counts[value] = self._counts.get(value, 0) + 1
        if value > self._max_value:
            self._max_value = value

    def remove(self, value: int) -> None:
        """Remove one occurrence of *value*. O(1) amortized.

        When the current max is removed and no duplicates remain, finding
        the new max is O(distinct_values) — typically < 10.
        """
        count = self._counts.get(value, 0)
        if count <= 0:
            return
        if count == 1:
            del self._counts[value]
            if value == self._max_value:
                self._max_value = max(self._counts) if self._counts else 0
        else:
            self._counts[value] = count - 1

    def replace(self, old_value: int, new_value: int) -> None:
        """Replace one occurrence of *old_value* with *new_value*. O(1) amortized."""
        if old_value == new_value:
            return
        self.remove(old_value)
        self.add(new_value)

    @property
    def max(self) -> int:
        """Current maximum. O(1)."""
        return self._max_value

    def rebuild(self, values: list[int]) -> None:
        """Rebuild from a list of values. O(n)."""
        self._counts.clear()
        self._max_value = 0
        for v in values:
            self._counts[v] = self._counts.get(v, 0) + 1
            if v > self._max_value:
                self._max_value = v

    def clear(self) -> None:
        """Reset. O(1)."""
        self._counts.clear()
        self._max_value = 0

    def __repr__(self) -> str:
        return f"MaxTracker(max={self._max_value}, distinct={len(self._counts)})"
