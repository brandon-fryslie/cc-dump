"""View override store — separates mutable TUI state from immutable domain blocks.

// [LAW:one-source-of-truth] View overrides have exactly one store — ViewOverrides.
// [LAW:single-enforcer] Visibility resolution reads overrides at one site.
// [LAW:one-way-deps] Depends on formatting types only.

Owned by ConversationView. Serializable for hot-reload via to_dict/from_dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from cc_dump.formatting import Category, VisState, FormattedBlock


@dataclass
class BlockViewState:
    """Per-block view state, keyed by block_id."""

    expanded: bool | None = None  # click toggle override
    force_vis: VisState | None = None  # search override
    expandable: bool = False  # renderer-computed


@dataclass
class RegionViewState:
    """Per-region view state, keyed by (block_id, region_index)."""

    expanded: bool | None = None  # click toggle override
    strip_range: tuple[int, int] | None = None  # renderer-computed


class ViewOverrides:
    """Dict-based container for all mutable view state extracted from FormattedBlock.

    Auto-creates entries on miss (get_block/get_region). Only entries that are
    actually touched consume memory.
    """

    def __init__(self):
        self._blocks: dict[int, BlockViewState] = {}
        self._regions: dict[tuple[int, int], RegionViewState] = {}
        self._search_block_ids: set[int] = set()

    def get_block(self, block_id: int) -> BlockViewState:
        """Get or create BlockViewState for a block_id."""
        state = self._blocks.get(block_id)
        if state is None:
            state = BlockViewState()
            self._blocks[block_id] = state
        return state

    def get_region(self, block_id: int, idx: int) -> RegionViewState:
        """Get or create RegionViewState for a (block_id, region_index)."""
        key = (block_id, idx)
        state = self._regions.get(key)
        if state is None:
            state = RegionViewState()
            self._regions[key] = state
        return state

    def clear_category(self, blocks: Iterable[FormattedBlock], category: Category) -> None:
        """Reset expanded overrides for all blocks matching a category.

        Imports get_category at call time for hot-reload safety.
        Recursively walks children.
        """
        import cc_dump.tui.rendering

        def _walk(block_list):
            for block in block_list:
                block_cat = cc_dump.tui.rendering.get_category(block)
                if block_cat == category:
                    bvs = self._blocks.get(block.block_id)
                    if bvs is not None:
                        bvs.expanded = None
                    # Clear region overrides
                    for region in block.content_regions:
                        key = (block.block_id, region.index)
                        rvs = self._regions.get(key)
                        if rvs is not None:
                            rvs.expanded = None
                _walk(getattr(block, "children", []))

        _walk(list(blocks))

    def clear_search(self) -> None:
        """Bulk-clear all force_vis set during search."""
        for block_id in self._search_block_ids:
            bvs = self._blocks.get(block_id)
            if bvs is not None:
                bvs.force_vis = None
        self._search_block_ids.clear()

    def to_dict(self) -> dict:
        """Serialize for hot-reload state transfer.

        force_vis is not serialized — search state is transient and cleared on reload.
        """
        blocks = {}
        for bid, bvs in self._blocks.items():
            entry = {}
            if bvs.expanded is not None:
                entry["expanded"] = bvs.expanded
            if bvs.expandable:
                entry["expandable"] = True
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
                expanded=entry.get("expanded"),
                expandable=entry.get("expandable", False),
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
