"""Tests for shared block-location navigation helpers."""

from cc_dump.tui.location_navigation import BlockLocation, go_to_location, resolve_scroll_key


class _Turn:
    def __init__(self, blocks, block_strip_map, flat_blocks):
        self.blocks = blocks
        self.block_strip_map = block_strip_map
        self._flat_blocks = flat_blocks


class _Conv:
    def __init__(self, turns):
        self._turns = turns
        self.ensure_calls: list[int] = []
        self.scroll_calls: list[tuple[int, int]] = []

    def ensure_turn_rendered(self, turn_index: int):
        self.ensure_calls.append(turn_index)

    def scroll_to_block(self, turn_index: int, block_index: int):
        self.scroll_calls.append((turn_index, block_index))


def test_resolve_scroll_key_uses_block_identity_when_available():
    top = object()
    child = object()
    turn = _Turn(
        blocks=[top],
        block_strip_map={0: 0, 7: 3},
        flat_blocks=[top, child],
    )
    location = BlockLocation(turn_index=0, block_index=0, block=child)
    assert resolve_scroll_key(turn, location) == 7


def test_resolve_scroll_key_falls_back_to_hier_index():
    top = object()
    turn = _Turn(
        blocks=[top],
        block_strip_map={0: 0},
        flat_blocks=[top],
    )
    location = BlockLocation(turn_index=0, block_index=0, block=object())
    assert resolve_scroll_key(turn, location) == 0


def test_go_to_location_runs_rerender_and_scroll():
    block = object()
    turn = _Turn(
        blocks=[block],
        block_strip_map={0: 0},
        flat_blocks=[block],
    )
    conv = _Conv([turn])
    calls = {"rerender": 0}

    ok = go_to_location(
        conv,
        BlockLocation(turn_index=0, block_index=0, block=block),
        rerender=lambda: calls.__setitem__("rerender", calls["rerender"] + 1),
    )

    assert ok is True
    assert calls["rerender"] == 1
    assert conv.ensure_calls == [0]
    assert conv.scroll_calls == [(0, 0)]


def test_go_to_location_rejects_invalid_indices():
    conv = _Conv([_Turn(blocks=[], block_strip_map={}, flat_blocks=[])])
    assert go_to_location(conv, BlockLocation(turn_index=1, block_index=0)) is False
    assert go_to_location(conv, BlockLocation(turn_index=0, block_index=1)) is False
