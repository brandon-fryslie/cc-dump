"""View override store — separates mutable TUI state from immutable domain blocks.

// [LAW:one-source-of-truth] View overrides have exactly one store — ViewOverrides.
// [LAW:single-enforcer] Visibility resolution reads overrides at one site.
// [LAW:one-way-deps] Depends on formatting types plus rendering category seam.

Owned by ConversationView. Serializable for hot-reload via to_dict/from_dict.
"""

from __future__ import annotations

from dataclasses import dataclass

from cc_dump.core.formatting import ALWAYS_VISIBLE, Category, VisState


@dataclass
class BlockViewState:
    """Per-block view state, keyed by block_id."""

    expandable: bool = False  # renderer-computed
    expanded: bool | None = None  # user click override; None means category default
    vis_override: VisState | None = None  # programmatic override (search reveal); not serialized


@dataclass
class RegionViewState:
    """Per-region view state, keyed by (block_id, region_index)."""

    expanded: bool | None = None  # click toggle override
    strip_range: tuple[int, int] | None = None  # renderer-computed


class ViewOverrides:
    """Dict-based container for all mutable view state extracted from FormattedBlock.

    Auto-creates entries on miss (get_block/get_region). Only entries that are
    actually touched consume memory.

    // [LAW:one-source-of-truth] Category index tracks block_id → category for O(overrides)
    // clearing instead of O(all blocks) tree walk.
    """

    def __init__(self):
        self._blocks: dict[int, BlockViewState] = {}
        self._regions: dict[tuple[int, int], RegionViewState] = {}
        # // [LAW:one-source-of-truth] Category index populated by register_block/unregister_block.
        self._block_categories: dict[int, Category | None] = {}
        # // [LAW:one-source-of-truth] Active search reveal tracking — at most one block + region.
        self._active_reveal_block_id: int | None = None
        self._active_reveal_region: tuple[int, int] | None = None

    def get_block(self, block_id: int) -> BlockViewState:
        """Get or create BlockViewState for a block_id."""
        state = self._blocks.get(block_id)
        if state is None:
            state = BlockViewState()
            self._blocks[block_id] = state
        return state

    def block_state(self, block_id: int) -> BlockViewState | None:
        """Read BlockViewState for block_id without creating an entry."""
        return self._blocks.get(block_id)

    def get_region(self, block_id: int, idx: int) -> RegionViewState:
        """Get or create RegionViewState for a (block_id, region_index)."""
        key = (block_id, idx)
        state = self._regions.get(key)
        if state is None:
            state = RegionViewState()
            self._regions[key] = state
        return state

    # ─── Block registration (category index) ─────────────────────────────

    def register_block(self, block_id: int, category: Category | None) -> None:
        """Register a block's category for O(overrides) clearing."""
        self._block_categories[block_id] = category

    def unregister_block(self, block_id: int) -> None:
        """Remove a block from the category index."""
        self._block_categories.pop(block_id, None)

    # ─── Search reveal via vis_override ──────────────────────────────────

    def set_search_reveal(
        self,
        *,
        block_id: int,
        region_index: int | None = None,
    ) -> bool:
        """Set search reveal on a block (and optionally a region).

        // [LAW:one-source-of-truth] Search reveal is a vis_override on BlockViewState +
        // expanded override on RegionViewState. No separate reveal sets.

        Clears previous reveal before setting new one. Returns whether state changed.
        """
        next_reveal = (block_id, region_index)
        prev_reveal = (self._active_reveal_block_id, self._active_reveal_region)
        # Normalize previous region to just region_index for comparison
        prev_region_index = self._active_reveal_region[1] if self._active_reveal_region else None
        if (block_id, region_index) == (self._active_reveal_block_id, prev_region_index):
            return False  # no change

        # Clear previous reveal
        self._clear_active_reveal()

        # Set new block vis_override
        block_vs = self.get_block(block_id)
        block_vs.vis_override = ALWAYS_VISIBLE

        # Set new region expanded override
        if region_index is not None:
            region_vs = self.get_region(block_id, region_index)
            region_vs.expanded = True
            self._active_reveal_region = (block_id, region_index)
        else:
            self._active_reveal_region = None

        self._active_reveal_block_id = block_id
        return True

    def clear_search_reveal(self) -> bool:
        """Clear active search reveal. Returns whether state changed."""
        if self._active_reveal_block_id is None:
            return False
        self._clear_active_reveal()
        return True

    def _clear_active_reveal(self) -> None:
        """Clear the currently active reveal's overrides."""
        if self._active_reveal_block_id is not None:
            block_vs = self._blocks.get(self._active_reveal_block_id)
            if block_vs is not None:
                block_vs.vis_override = None
        if self._active_reveal_region is not None:
            region_vs = self._regions.get(self._active_reveal_region)
            if region_vs is not None:
                region_vs.expanded = None
        self._active_reveal_block_id = None
        self._active_reveal_region = None

    # ─── Category clearing ───────────────────────────────────────────────

    def clear_category(self, category: Category) -> None:
        """Reset all overrides for blocks matching a category.

        // [LAW:one-source-of-truth] Uses _block_categories index — O(registered blocks in category).
        Clears both block-level (expanded, vis_override) and region-level (expanded) overrides.
        """
        # Collect matching block_ids
        matching_bids = [
            bid for bid, cat in self._block_categories.items() if cat == category
        ]

        for bid in matching_bids:
            block_vs = self._blocks.get(bid)
            if block_vs is not None:
                block_vs.expanded = None
                block_vs.vis_override = None

            # Clear regions belonging to this block
            # Iterate all regions and clear those with matching block_id
            for key, rvs in self._regions.items():
                if key[0] == bid:
                    rvs.expanded = None

        # If active reveal was in this category, clear tracking
        if self._active_reveal_block_id is not None:
            if self._block_categories.get(self._active_reveal_block_id) == category:
                self._active_reveal_block_id = None
                self._active_reveal_region = None

    # ─── Serialization ───────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize for hot-reload state transfer.

        vis_override and _block_categories are transient — not serialized.
        """
        blocks = {}
        for bid, bvs in self._blocks.items():
            entry = {}
            if bvs.expandable:
                entry["expandable"] = True
            if bvs.expanded is not None:
                entry["expanded"] = bvs.expanded
            # vis_override is transient — not serialized
            if entry:
                blocks[bid] = entry

        regions = {}
        for (bid, idx), rvs in self._regions.items():
            entry = {}
            if rvs.expanded is not None:
                entry["expanded"] = rvs.expanded
            # strip_range is renderer-computed, transient — not serialized
            if entry:
                regions[f"{bid},{idx}"] = entry

        return {"blocks": blocks, "regions": regions}

    @classmethod
    def from_dict(cls, data: dict) -> ViewOverrides:
        """Deserialize from hot-reload state."""
        vo = cls()
        for bid_str, entry in data.get("blocks", {}).items():
            bid = int(bid_str) if isinstance(bid_str, str) else bid_str
            bvs = BlockViewState(
                expandable=entry.get("expandable", False),
                expanded=entry.get("expanded"),
            )
            vo._blocks[bid] = bvs

        for key_str, entry in data.get("regions", {}).items():
            parts = key_str.split(",") if isinstance(key_str, str) else key_str
            if isinstance(parts, (list, tuple)) and len(parts) == 2:
                bid, idx = int(parts[0]), int(parts[1])
            else:
                continue
            rvs = RegionViewState(expanded=entry.get("expanded"))
            vo._regions[(bid, idx)] = rvs

        return vo
