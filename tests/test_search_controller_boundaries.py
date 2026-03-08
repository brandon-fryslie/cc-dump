"""Boundary tests for search controller ↔ ConversationView seams."""

from __future__ import annotations

import types

import cc_dump.app.view_store
import cc_dump.tui.search_controller as ctrl
from cc_dump.core.formatting import TextContentBlock
from cc_dump.tui.search import SearchMode, SearchPhase, SearchState


class _Conv:
    def __init__(self, turns):
        self._turns_snapshot = turns
        self.snapshot_calls = 0
        self.anchor_calls = 0
        self.restore_calls: list[float] = []
        self.rerender_calls = 0

    def get_search_turns_snapshot(self):
        self.snapshot_calls += 1
        return types.SimpleNamespace(turns=tuple(self._turns_snapshot))

    def capture_scroll_anchor(self) -> None:
        self.anchor_calls += 1

    def restore_scroll_y(self, y: float) -> None:
        self.restore_calls.append(y)

    def rerender(self, _filters, search_ctx=None):
        _ = search_ctx
        self.rerender_calls += 1


class _App:
    def __init__(self, state: SearchState, store, conv: _Conv | None):
        self._search_state = state
        self._view_store = store
        self._conv = conv
        self.active_filters = {"assistant": types.SimpleNamespace(visible=True, full=True, expanded=True)}

    def _get_conv(self):
        return self._conv


def _make_state_and_store() -> tuple[SearchState, object]:
    store = cc_dump.app.view_store.create()
    state = SearchState(store)
    return state, store


def test_run_search_uses_public_turn_snapshot():
    state, store = _make_state_and_store()
    state.query = "needle"
    state.modes = SearchMode.CASE_INSENSITIVE
    turns = [types.SimpleNamespace(is_streaming=False, blocks=[TextContentBlock(content="needle")])]
    conv = _Conv(turns)
    app = _App(state, store, conv)

    ctrl.run_search(app)

    assert conv.snapshot_calls == 1
    assert len(state.matches) == 1
    assert state.matches[0].turn_index == 0


def test_exit_search_keep_position_uses_public_anchor_capture():
    state, store = _make_state_and_store()
    state.phase = SearchPhase.NAVIGATING
    conv = _Conv([])
    app = _App(state, store, conv)

    ctrl.exit_search_keep_position(app)

    assert conv.anchor_calls == 1
    assert conv.rerender_calls == 1


def test_exit_search_restore_position_uses_public_scroll_restore():
    state, store = _make_state_and_store()
    state.phase = SearchPhase.NAVIGATING
    state.saved_scroll_y = 42.0
    conv = _Conv([])
    app = _App(state, store, conv)

    ctrl.exit_search_restore_position(app)

    assert conv.restore_calls == [42.0]
    assert state.saved_scroll_y is None


def test_commit_search_does_not_invoke_navigation(monkeypatch):
    state, store = _make_state_and_store()
    state.query = "needle"
    state.modes = SearchMode.CASE_INSENSITIVE
    turns = [types.SimpleNamespace(is_streaming=False, blocks=[TextContentBlock(content="needle")])]
    conv = _Conv(turns)
    app = _App(state, store, conv)

    called = {"navigate": 0}
    monkeypatch.setattr(
        ctrl,
        "navigate_to_current",
        lambda _app: called.__setitem__("navigate", called["navigate"] + 1),
    )

    ctrl.commit_search(app)

    assert state.phase == SearchPhase.NAVIGATING
    assert called["navigate"] == 0
