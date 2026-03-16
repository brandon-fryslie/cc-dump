"""Tests for ConversationView public seam methods used by search."""

from types import SimpleNamespace

import cc_dump.core.formatting
from cc_dump.tui.widget_factory import ConversationView, ScrollAnchor, TurnData


def test_get_search_turns_snapshot_returns_immutable_snapshot():
    conv = ConversationView()
    marker = object()
    conv._turns = [marker]  # test seam shape only

    snapshot = conv.get_search_turns_snapshot()
    assert snapshot.turns == (marker,)


def test_turn_data_rebuild_block_derivatives_refreshes_searchable_blocks():
    initial = cc_dump.core.formatting.TextContentBlock(content="alpha")
    td = TurnData(turn_index=0, blocks=[initial], strips=[])

    assert td.searchable_blocks == ((0, initial),)

    replacement = cc_dump.core.formatting.TextContentBlock(content="beta")
    td.blocks = [replacement]
    td.rebuild_block_derivatives()

    assert td.searchable_blocks == ((0, replacement),)


def test_capture_scroll_anchor_sets_anchor_from_compute(monkeypatch):
    conv = ConversationView()
    anchor = ScrollAnchor(turn_index=3, line_in_turn=2)
    monkeypatch.setattr(conv, "_compute_anchor_from_scroll", lambda: anchor)

    conv.capture_scroll_anchor()

    assert conv._scroll_anchor == anchor


def test_restore_scroll_y_delegates_to_scroll_to_without_animation(monkeypatch):
    conv = ConversationView()
    calls: list[dict[str, object]] = []
    anchor = ScrollAnchor(turn_index=1, line_in_turn=3)

    monkeypatch.setattr(
        conv,
        "scroll_to",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(conv, "_compute_anchor_from_scroll", lambda: anchor)

    conv.restore_scroll_y(42.5)

    assert calls == [{"y": 42.5, "animate": False}]
    assert conv._scroll_anchor == anchor


def test_block_expansion_seam_set_toggle_clear():
    conv = ConversationView()
    block = cc_dump.core.formatting.TextContentBlock(content="Hello")
    conv._turns = [  # test seam shape only
        TurnData(
            turn_index=0,
            blocks=[block],
            strips=[],
        )
    ]
    conv._index_blocks([block])
    conv._view_overrides.get_block(block.block_id).expandable = True
    conv._last_filters = {"assistant": cc_dump.core.formatting.ALWAYS_VISIBLE}

    assert conv.set_block_expansion(block.block_id, True, rerender=False) is True
    assert conv._view_overrides.get_block(block.block_id).expanded is True

    assert conv.toggle_block_expansion(block.block_id, rerender=False) is True
    assert conv._view_overrides.get_block(block.block_id).expanded is False

    assert conv.clear_block_expansion(block.block_id, rerender=False) is True
    assert conv._view_overrides.get_block(block.block_id).expanded is None


def test_block_expansion_seam_noop_for_non_expandable():
    conv = ConversationView()
    block = cc_dump.core.formatting.TextContentBlock(content="Hello")
    conv._turns = [
        TurnData(
            turn_index=0,
            blocks=[block],
            strips=[],
        )
    ]
    conv._index_blocks([block])

    assert conv.set_block_expansion(block.block_id, True, rerender=False) is False
    assert conv.toggle_block_expansion(block.block_id, rerender=False) is False
    assert conv.clear_block_expansion(block.block_id, rerender=False) is False
    assert conv._view_overrides.get_block(block.block_id).expanded is None


def test_set_block_expansion_captures_anchor_before_rerender(monkeypatch):
    conv = ConversationView()
    block = cc_dump.core.formatting.TextContentBlock(content="Hello")
    conv._turns = [
        TurnData(
            turn_index=0,
            blocks=[block],
            strips=[],
        )
    ]
    conv._index_blocks([block])
    conv._view_overrides.get_block(block.block_id).expandable = True
    conv._last_filters = {"assistant": cc_dump.core.formatting.ALWAYS_VISIBLE}
    conv._last_search_ctx = object()

    calls: list[object] = []
    monkeypatch.setattr(
        ConversationView,
        "is_attached",
        property(lambda _self: True),
    )
    monkeypatch.setattr(
        ConversationView,
        "_is_following",
        property(lambda _self: False),
    )
    monkeypatch.setattr(conv, "capture_scroll_anchor", lambda: calls.append("capture"))
    monkeypatch.setattr(
        conv,
        "rerender",
        lambda filters, search_ctx=None: calls.append(("rerender", filters, search_ctx)),
    )

    assert conv.set_block_expansion(block.block_id, True, rerender=True) is True
    assert calls[0] == "capture"
    assert calls[1] == ("rerender", conv._last_filters, conv._last_search_ctx)


def test_clear_category_overrides_clears_block_expansion_for_category():
    conv = ConversationView()
    user_block = cc_dump.core.formatting.TextContentBlock(
        content="u",
        category=cc_dump.core.formatting.Category.USER,
    )
    assistant_block = cc_dump.core.formatting.TextContentBlock(
        content="a",
        category=cc_dump.core.formatting.Category.ASSISTANT,
    )
    conv._turns = [
        TurnData(
            turn_index=0,
            blocks=[user_block, assistant_block],
            strips=[],
        )
    ]

    conv._view_overrides.get_block(user_block.block_id).expanded = False
    conv._view_overrides.get_block(assistant_block.block_id).expanded = False

    conv.clear_category_overrides(cc_dump.core.formatting.Category.USER)

    assert conv._view_overrides.get_block(user_block.block_id).expanded is None
    assert conv._view_overrides.get_block(assistant_block.block_id).expanded is False


def test_iter_blocks_with_descendants_preserves_turn_order():
    conv = ConversationView()
    first = cc_dump.core.formatting.TextContentBlock(content="first")
    second = cc_dump.core.formatting.TextContentBlock(content="second")
    conv._turns = [
        TurnData(turn_index=0, blocks=[first], strips=[]),
        TurnData(turn_index=1, blocks=[second], strips=[]),
    ]

    ordered = list(conv._iter_blocks_with_descendants())

    assert ordered == [first, second]


def test_reveal_search_match_sets_temporary_reveal_state(monkeypatch):
    conv = ConversationView()
    block = cc_dump.core.formatting.TextContentBlock(content="needle")
    conv._turns = [
        TurnData(
            turn_index=0,
            blocks=[block],
            strips=[],
            block_strip_map={0: 0},
            _flat_blocks=[block],
        )
    ]
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(conv, "ensure_turn_rendered", lambda _idx: None)
    monkeypatch.setattr(conv, "scroll_to_block", lambda turn_index, block_index: calls.append((turn_index, block_index)))

    match = SimpleNamespace(
        turn_index=0,
        block_index=0,
        block=block,
        region_index=0,
    )
    assert conv.reveal_search_match(match, rerender=False) is True
    assert conv._view_overrides.has_search_reveal_block(block.block_id) is True
    assert conv._view_overrides.has_search_reveal_region(block.block_id, 0) is True
    assert calls == [(0, 0)]


def test_clear_search_reveal_clears_temporary_state():
    conv = ConversationView()
    conv._view_overrides.set_search_reveal(block_id=1, region_index=0)

    assert conv.clear_search_reveal(rerender=False) is True
    assert conv._view_overrides.has_search_reveal_block(1) is False
    assert conv._view_overrides.has_search_reveal_region(1, 0) is False


def test_clear_search_reveal_honors_rerender_when_state_is_already_clear(monkeypatch):
    conv = ConversationView()
    calls: list[tuple[object, object]] = []
    marker = object()
    conv._last_search_ctx = marker
    monkeypatch.setattr(
        ConversationView,
        "is_attached",
        property(lambda _self: True),
    )
    monkeypatch.setattr(
        conv,
        "rerender",
        lambda filters, search_ctx=None: calls.append((filters, search_ctx)),
    )

    changed = conv.clear_search_reveal(search_ctx=None, rerender=True)

    assert changed is False
    assert calls == [(conv._last_filters, marker)]
