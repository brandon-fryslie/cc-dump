"""Tests for extended search keyboard shortcuts."""

from types import SimpleNamespace

import cc_dump.tui.search_controller as ctrl
from cc_dump.tui.search import SearchMode


class _State:
    def __init__(self, query: str, cursor_pos: int, modes: SearchMode = SearchMode(0)):
        self.query = query
        self.cursor_pos = cursor_pos
        self.modes = modes
        self.phase = None
        self.matches = []
        self.current_index = 0
        self.saved_filters = {}
        self.debounce_timer = None
        self.saved_scroll_y = None
        self.text_cache = {}


class _App:
    def __init__(self, state: _State):
        self._search_state = state


def _event(key: str, character: str | None = None):
    return SimpleNamespace(key=key, character=character)


def test_search_edit_ctrl_a_and_ctrl_e_move_cursor(monkeypatch):
    state = _State("hello world", 5)
    app = _App(state)
    monkeypatch.setattr(ctrl, "schedule_incremental_search", lambda _app: None)

    ctrl.handle_search_editing_key(app, _event("ctrl+a"))
    assert state.cursor_pos == 0
    ctrl.handle_search_editing_key(app, _event("ctrl+e"))
    assert state.cursor_pos == len("hello world")


def test_search_edit_ctrl_w_deletes_previous_word(monkeypatch):
    state = _State("alpha beta gamma", len("alpha beta "))
    app = _App(state)
    monkeypatch.setattr(ctrl, "schedule_incremental_search", lambda _app: None)

    ctrl.handle_search_editing_key(app, _event("ctrl+w"))
    assert state.query == "alpha gamma"
    assert state.cursor_pos == len("alpha ")


def test_search_edit_alt_b_and_alt_f_move_by_word(monkeypatch):
    state = _State("alpha beta gamma", len("alpha beta "))
    app = _App(state)
    monkeypatch.setattr(ctrl, "schedule_incremental_search", lambda _app: None)

    ctrl.handle_search_editing_key(app, _event("alt+b"))
    assert state.cursor_pos == len("alpha ")
    ctrl.handle_search_editing_key(app, _event("alt+f"))
    assert state.cursor_pos == len("alpha beta")


def test_search_edit_ctrl_u_and_ctrl_k_kill_ranges(monkeypatch):
    state = _State("alpha beta gamma", len("alpha "))
    app = _App(state)
    monkeypatch.setattr(ctrl, "schedule_incremental_search", lambda _app: None)

    ctrl.handle_search_editing_key(app, _event("ctrl+k"))
    assert state.query == "alpha "
    assert state.cursor_pos == len("alpha ")

    ctrl.handle_search_editing_key(app, _event("ctrl+u"))
    assert state.query == ""
    assert state.cursor_pos == 0


def test_search_edit_ctrl_h_aliases_backspace(monkeypatch):
    state = _State("hello", len("hello"))
    app = _App(state)
    monkeypatch.setattr(ctrl, "schedule_incremental_search", lambda _app: None)

    ctrl.handle_search_editing_key(app, _event("ctrl+h"))
    assert state.query == "hell"
    assert state.cursor_pos == len("hell")
