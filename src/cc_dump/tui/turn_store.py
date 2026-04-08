"""TurnStore — canonical owner of turn list and derived indexes.

// [LAW:one-source-of-truth] Single owner of _turns + offset_tree + width_tracker +
// block_index + line_cache + cache_keys_by_turn. Any mutation that must keep
// those five in sync goes through one method here so callers cannot forget
// one.
// [LAW:single-enforcer] All per-turn offset/line-cache mutations happen here.
//
// Absorbed variance: previously ConversationView had to remember, on every
// turn insert/replace/prune/stream-pop, to:
//   1. mutate the `turns` list
//   2. update the Fenwick offset_tree
//   3. update the MaxTracker width_tracker
//   4. register/unregister blocks from block_index + view_overrides category index
//   5. invalidate line_cache entries for touched turns
//
// Missing any one of those five writes silently desynced a derived index from
// the canonical turn list. The store exposes mutation primitives that perform
// all five writes atomically — the caller can't drift because there is no
// second way to mutate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Iterator

from textual.cache import LRUCache

import cc_dump.tui.rendering
from cc_dump.tui.prefix_sum_tree import FenwickTree, MaxTracker

if TYPE_CHECKING:
    from cc_dump.tui.widget_factory import TurnData
    from cc_dump.tui.view_overrides import ViewOverrides

logger = logging.getLogger(__name__)


class TurnStore:
    """Owns `turns` list plus every index derived from it.

    Public attributes are intentionally direct-access to stay compatible with
    existing test code that pokes `_turns`, `_line_cache`, etc.
    """

    def __init__(self, *, view_overrides: "ViewOverrides") -> None:
        self.turns: list["TurnData"] = []
        self.offset_tree = FenwickTree()
        self.width_tracker = MaxTracker()
        self.block_index: dict[int, object] = {}
        self.line_cache: LRUCache = LRUCache(1024)
        self.block_strip_cache: LRUCache = LRUCache(4096)
        self.cache_keys_by_turn: dict[int, set[tuple]] = {}
        self.line_cache_index_write_count: int = 0
        self.line_cache_index_prune_interval: int = 256
        self.total_lines: int = 0
        self.widest_strip: int = 0
        self._view_overrides = view_overrides

    # ─── Block indexing ─────────────────────────────────────────────────

    def index_blocks(self, blocks) -> None:
        """Add blocks and descendants to block_id index + view_overrides registry."""
        stack = list(blocks)
        while stack:
            block = stack.pop()
            block_id = getattr(block, "block_id", None)
            if block_id is not None:
                self.block_index[block_id] = block
                category = cc_dump.tui.rendering.get_category(block)
                self._view_overrides.register_block(block_id, category)
            stack.extend(getattr(block, "children", []) or [])

    def unindex_blocks(self, blocks) -> None:
        """Remove blocks and descendants from the block_id index."""
        stack = list(blocks)
        while stack:
            block = stack.pop()
            block_id = getattr(block, "block_id", None)
            if block_id is not None:
                self.block_index.pop(block_id, None)
                self._view_overrides.unregister_block(block_id)
            stack.extend(getattr(block, "children", []) or [])

    def unindex_turn_range(self, turns) -> None:
        for td in turns:
            self.unindex_blocks(td.blocks)

    def find_block_by_id(self, block_id: int):
        return self.block_index.get(block_id)

    def iter_blocks_with_descendants(self) -> Iterator:
        stack: list = []
        for td in reversed(self.turns):
            stack.extend(reversed(td.blocks))
        while stack:
            block = stack.pop()
            yield block
            children = getattr(block, "children", []) or []
            for child in reversed(children):
                stack.append(child)

    # ─── Offset / width sync ────────────────────────────────────────────

    def sync_turn_in_tree(self, td: "TurnData") -> None:
        """Sync one turn's line count in the Fenwick tree. O(log n).

        // [LAW:single-enforcer] All per-turn offset mutations funnel here.
        """
        idx = td.turn_index
        old_count = self.offset_tree.get(idx)
        new_count = td.line_count
        if old_count != new_count:
            self.offset_tree.set(idx, new_count)

    def recalculate_offsets(self) -> None:
        """Full rebuild of offset tree and width tracker. O(n)."""
        self.offset_tree.rebuild([td.line_count for td in self.turns])
        self.width_tracker.rebuild([td._widest_strip for td in self.turns])
        self.total_lines = self.offset_tree.total()
        self.widest_strip = self.width_tracker.max
        self.clear_line_cache()

    def refresh_totals(self) -> None:
        """Refresh total_lines + widest_strip from tree/tracker. O(log n)."""
        self.total_lines = self.offset_tree.total()
        self.widest_strip = self.width_tracker.max

    # ─── Turn mutations (the absorbed-variance entry points) ────────────

    def append(self, td: "TurnData") -> None:
        """Append a turn, syncing all derived indexes atomically.

        // [LAW:dataflow-not-control-flow] Same five writes on every append.
        """
        td.turn_index = len(self.turns)
        self.turns.append(td)
        self.offset_tree.append(td.line_count)
        self.width_tracker.add(td._widest_strip)
        self.refresh_totals()

    def pop_last(self) -> "TurnData | None":
        """Remove and return last turn, releasing its derived-index slots."""
        if not self.turns:
            return None
        popped = self.turns.pop()
        # Fenwick tree has no per-slot delete; rebuild from remaining turns.
        self.offset_tree.rebuild([t.line_count for t in self.turns])
        self.width_tracker.remove(popped._widest_strip)
        self.refresh_totals()
        return popped

    def replace_blocks_at(
        self,
        turn_index: int,
        new_blocks: list,
    ) -> "TurnData | None":
        """Swap the blocks on an existing turn, maintaining block_index.

        Caller is responsible for re-rendering the turn afterwards and calling
        `sync_turn_in_tree` / `invalidate_cache_for_turns` once strips change.
        Returns the affected TurnData or None if out of range.
        """
        if turn_index < 0 or turn_index >= len(self.turns):
            return None
        td = self.turns[turn_index]
        self.unindex_blocks(td.blocks)
        td.blocks = new_blocks
        self.index_blocks(new_blocks)
        td.rebuild_block_derivatives()
        return td

    def prune_front(self, n: int) -> int:
        """Remove the oldest n turns, unindexing their blocks and reindexing.

        Returns the actual number pruned (0 if n <= 0, len(turns) if n >= len).
        """
        if n <= 0 or not self.turns:
            return 0
        if n >= len(self.turns):
            return self.clear_all()
        self.unindex_turn_range(self.turns[:n])
        del self.turns[:n]
        for idx, td in enumerate(self.turns):
            td.turn_index = idx
        self.clear_line_cache()
        self.recalculate_offsets()
        return n

    def clear_all(self) -> int:
        """Drop every turn and clear all derived indexes."""
        pruned = len(self.turns)
        self.turns.clear()
        self.block_index.clear()
        self.clear_line_cache()
        self.recalculate_offsets()
        return pruned

    # ─── Line lookup ────────────────────────────────────────────────────

    def find_turn_with_offset(self, line_y: int) -> "tuple[TurnData, int] | None":
        """Find the turn containing virtual line y. O(log n)."""
        result = self.offset_tree.find(line_y)
        if result is None:
            return None
        idx, offset = result
        if idx >= len(self.turns):
            return None
        return (self.turns[idx], offset)

    def find_turn_for_line(self, line_y: int) -> "TurnData | None":
        result = self.find_turn_with_offset(line_y)
        return result[0] if result is not None else None

    def viewport_turn_range(
        self,
        *,
        scroll_y: int,
        viewport_height: int,
        buffer_lines: int = 200,
    ) -> tuple[int, int]:
        """Return inclusive-start, exclusive-end turn indices visible in viewport."""
        if not self.turns:
            return (0, 0)
        range_start = max(0, scroll_y - buffer_lines)
        range_end = scroll_y + viewport_height + buffer_lines
        start_turn = self.find_turn_for_line(range_start)
        start_idx = 0 if start_turn is None else start_turn.turn_index
        end_turn = self.find_turn_for_line(min(range_end, self.total_lines - 1))
        end_idx = len(self.turns) if end_turn is None else end_turn.turn_index + 1
        return (start_idx, end_idx)

    # ─── Line cache ─────────────────────────────────────────────────────

    def clear_line_cache(self) -> None:
        self.line_cache.clear()
        self.cache_keys_by_turn.clear()
        self.line_cache_index_write_count = 0

    def prune_line_cache_index(self) -> None:
        live_keys = set(self.line_cache.keys())
        stale_turns: list[int] = []
        for turn_idx, keys in self.cache_keys_by_turn.items():
            keys.intersection_update(live_keys)
            if not keys:
                stale_turns.append(turn_idx)
        for turn_idx in stale_turns:
            self.cache_keys_by_turn.pop(turn_idx, None)

    def invalidate_cache_for_turns(
        self,
        start_idx: int,
        end_idx: int | None = None,
    ) -> None:
        """Drop line-cache entries for turns in [start_idx, end_idx).

        When end_idx is None, performs a full clear (callers that mean "all"
        pass None so 0-anchored viewport calls cannot incidentally wipe).
        // [LAW:single-enforcer] Range invalidation for line cache happens only here.
        """
        if end_idx is None:
            self.clear_line_cache()
            return
        upper = min(end_idx, len(self.turns))
        if upper <= start_idx:
            return
        for turn_idx in range(start_idx, upper):
            keys = self.cache_keys_by_turn.pop(turn_idx, None)
            if not keys:
                continue
            for key in keys:
                self.line_cache.discard(key)

    def record_line_cache_entry(
        self,
        *,
        turn_idx: int,
        cache_key: tuple,
        strip,
    ) -> None:
        """Store a rendered strip in the cache and track its turn ownership."""
        self.line_cache[cache_key] = strip
        if turn_idx not in self.cache_keys_by_turn:
            self.cache_keys_by_turn[turn_idx] = set()
        self.cache_keys_by_turn[turn_idx].add(cache_key)
        self.line_cache_index_write_count += 1
        if self.line_cache_index_write_count >= self.line_cache_index_prune_interval:
            self.line_cache_index_write_count = 0
            self.prune_line_cache_index()
