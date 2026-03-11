"""Shared location navigation helpers for conversation turns.

// [LAW:one-source-of-truth] BlockLocation is the canonical jump target shape.
// [LAW:single-enforcer] go_to_location is the sole turn/block jump executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class BlockLocation:
    """A concrete location in the conversation view."""

    turn_index: int
    block_index: int
    block_id: int | None = None
    block: object | None = None


def resolve_scroll_key(turn, location: BlockLocation) -> int:
    """Resolve the block_strip_map key for a location.

    Uses identity matching against turn._flat_blocks when an exact block object
    is available, otherwise falls back to hierarchical block_index.
    """
    scroll_key = location.block_index
    if location.block is None:
        return scroll_key

    block_strip_keys = list(turn.block_strip_map.keys())
    for idx, flat_block in enumerate(turn._flat_blocks):
        if flat_block is location.block and idx < len(block_strip_keys):
            return block_strip_keys[idx]
    return scroll_key


def _turn_for_location(conv, location: BlockLocation):
    if location.turn_index < 0 or location.turn_index >= len(conv._turns):
        return None
    turn = conv._turns[location.turn_index]
    if location.block_index < 0 or location.block_index >= len(turn.blocks):
        return None
    return turn


def _location_block_id(turn, location: BlockLocation) -> int | None:
    if location.block_id is not None:
        return location.block_id
    target_block = location.block if location.block is not None else turn.blocks[location.block_index]
    target_block_id = getattr(target_block, "block_id", None)
    return target_block_id if isinstance(target_block_id, int) else None


def _expand_location_block(conv, turn, location: BlockLocation) -> None:
    target_block_id = _location_block_id(turn, location)
    set_block_expansion = getattr(conv, "set_block_expansion", None)
    if target_block_id is None or not callable(set_block_expansion):
        return
    # // [LAW:locality-or-seam] Navigation reveals block content through ConversationView seam.
    set_block_expansion(target_block_id, True, rerender=False)


def go_to_location(
    conv,
    location: BlockLocation,
    *,
    rerender: Callable[[], None] | None = None,
) -> bool:
    """Navigate to a block location in the conversation.

    Returns True when navigation succeeded, False when the location is invalid.
    """
    turn = _turn_for_location(conv, location)
    if turn is None:
        return False

    _expand_location_block(conv, turn, location)

    if rerender is not None:
        rerender()

    conv.ensure_turn_rendered(location.turn_index)
    turn = conv._turns[location.turn_index]
    scroll_key = resolve_scroll_key(turn, location)
    conv.scroll_to_block(location.turn_index, scroll_key)
    return True
