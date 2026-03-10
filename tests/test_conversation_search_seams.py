"""Tests for ConversationView public seam methods used by search."""

from cc_dump.tui.widget_factory import ConversationView, ScrollAnchor


def test_get_search_turns_snapshot_returns_immutable_snapshot():
    conv = ConversationView()
    marker = object()
    conv._turns = [marker]  # test seam shape only

    snapshot = conv.get_search_turns_snapshot()
    assert snapshot.turns == (marker,)


def test_capture_scroll_anchor_sets_anchor_from_compute(monkeypatch):
    conv = ConversationView()
    anchor = ScrollAnchor(turn_index=3, block_index=1, line_in_block=2)
    monkeypatch.setattr(conv, "_compute_anchor_from_scroll", lambda: anchor)

    conv.capture_scroll_anchor()

    assert conv._scroll_anchor == anchor


def test_restore_scroll_y_delegates_to_scroll_to_without_animation(monkeypatch):
    conv = ConversationView()
    calls: list[dict[str, object]] = []
    anchor = ScrollAnchor(turn_index=1, block_index=2, line_in_block=3)

    monkeypatch.setattr(
        conv,
        "scroll_to",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(conv, "_compute_anchor_from_scroll", lambda: anchor)

    conv.restore_scroll_y(42.5)

    assert calls == [{"y": 42.5, "animate": False}]
    assert conv._scroll_anchor == anchor
