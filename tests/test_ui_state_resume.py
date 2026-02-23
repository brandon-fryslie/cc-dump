"""Tests for app-level UI state export and resume application."""

import queue
from types import SimpleNamespace

import cc_dump.app.domain_store
import cc_dump.app.view_store
from cc_dump.tui.app import CcDumpApp


def _make_app():
    state = {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
        "current_session": None,
    }
    return CcDumpApp(
        event_queue=queue.Queue(),
        state=state,
        router=SimpleNamespace(stop=lambda: None),
        view_store=cc_dump.app.view_store.create(),
        domain_store=cc_dump.app.domain_store.DomainStore(),
    )


def test_export_ui_state_includes_view_and_app_fields(monkeypatch):
    app = _make_app()
    app.show_logs = True
    app.show_info = False
    app._view_store.set("panel:active", "stats")
    app._view_store.set("search:query", "hello")

    conv_states = {
        "__default__": {"follow_state": "active"},
        "sess-a": {"follow_state": "off"},
    }
    app._session_conv_ids = {
        "__default__": "conversation-view",
        "sess-a": "conversation-view-1",
    }
    app._active_session_key = "__default__"

    class _Conv:
        def __init__(self, state):
            self._state = state

        def get_state(self):
            return self._state

    monkeypatch.setattr(
        app,
        "_get_conv",
        lambda session_key=None: _Conv(
            conv_states.get(
                "__default__" if session_key is None else session_key,
                {},
            )
        ),
    )
    monkeypatch.setattr(app, "_active_session_key_from_tabs", lambda: "__default__")

    exported = app.export_ui_state()
    assert exported["view_store"]["panel:active"] == "stats"
    assert exported["view_store"]["search:query"] == "hello"
    assert exported["app"]["show_logs"] is True
    assert exported["app"]["show_info"] is False
    assert exported["conv"]["follow_state"] == "active"
    assert exported["conversations"]["states"]["__default__"]["follow_state"] == "active"
    assert exported["conversations"]["states"]["sess-a"]["follow_state"] == "off"
    assert exported["conversations"]["active_session_key"] == "__default__"


def test_apply_resume_ui_state_preload_updates_store_and_app_flags():
    app = _make_app()
    app._resume_ui_state = {
        "view_store": {
            "panel:active": "stats",
            "search:query": "resume me",
            "vis:user": False,
        },
        "app": {"show_logs": True, "show_info": True},
    }

    app._apply_resume_ui_state_preload()

    assert app._view_store.get("panel:active") == "stats"
    assert app._view_store.get("search:query") == "resume me"
    assert app._view_store.get("vis:user") is False
    assert app.show_logs is True
    assert app.show_info is True


def test_apply_resume_ui_state_postload_restores_conv_state(monkeypatch):
    app = _make_app()
    app._resume_ui_state = {"conv": {"foo": "bar"}}
    calls = {"restore": None, "rerender": 0}

    class _Conv:
        def restore_state(self, state):
            calls["restore"] = state

        def rerender(self, _filters):
            calls["rerender"] += 1

    monkeypatch.setattr(app, "_get_conv", lambda session_key=None: _Conv())

    app._apply_resume_ui_state_postload()

    assert calls["restore"] == {"foo": "bar"}
    assert calls["rerender"] == 1


def test_apply_resume_ui_state_postload_restores_multi_session_state(monkeypatch):
    app = _make_app()
    app._resume_ui_state = {
        "conversations": {
            "states": {
                "__default__": {"follow_state": "active"},
                "sess-a": {"follow_state": "off"},
            },
            "active_session_key": "sess-a",
        }
    }

    class _Tabs:
        def __init__(self):
            self.active = "conversation-tab-main"

    class _Conv:
        def __init__(self):
            self.restored = None
            self.rerender_count = 0

        def restore_state(self, state):
            self.restored = state

        def rerender(self, _filters):
            self.rerender_count += 1

    convs = {
        "__default__": _Conv(),
        "sess-a": _Conv(),
    }
    tabs = _Tabs()
    app._session_tab_ids = {
        "__default__": "conversation-tab-main",
        "sess-a": "conversation-tab-main-1",
    }
    app._session_domain_stores["sess-a"] = cc_dump.app.domain_store.DomainStore()
    called_session_keys: list[str] = []

    monkeypatch.setattr(app, "_ensure_session_surface", lambda session_key: called_session_keys.append(session_key))
    monkeypatch.setattr(app, "_get_conv", lambda session_key=None: convs["__default__" if session_key is None else session_key])
    monkeypatch.setattr(app, "_get_conv_tabs", lambda: tabs)
    monkeypatch.setattr(app, "_sync_active_stream_footer", lambda: None)

    app._apply_resume_ui_state_postload()

    assert called_session_keys == ["__default__", "sess-a"]
    assert convs["__default__"].restored == {"follow_state": "active"}
    assert convs["sess-a"].restored == {"follow_state": "off"}
    assert convs["__default__"].rerender_count == 1
    assert convs["sess-a"].rerender_count == 1
    assert tabs.active == "conversation-tab-main-1"
    assert app._active_session_key == "sess-a"
    assert app._domain_store is app._session_domain_stores["sess-a"]


def test_active_resume_session_id_prefers_active_session_tab(monkeypatch):
    app = _make_app()
    app._session_id = "legacy-main"
    app._active_session_key = "sess-a"
    app._session_tab_ids["sess-a"] = "conversation-tab-main-1"

    monkeypatch.setattr(app, "_active_session_key_from_tabs", lambda: "sess-a")

    assert app._active_resume_session_id() == "sess-a"


def test_get_active_session_panel_state_reads_per_session_last_message(monkeypatch):
    app = _make_app()
    app._session_id = "legacy-main"
    app._active_session_key = "sess-a"
    app._session_tab_ids["sess-a"] = "conversation-tab-main-1"
    app._app_state["last_message_time"] = 10.0
    app._app_state["last_message_time_by_session"] = {
        "__default__": 11.0,
        "sess-a": 42.5,
    }

    monkeypatch.setattr(app, "_active_session_key_from_tabs", lambda: "sess-a")

    session_id, last_message_time = app._get_active_session_panel_state()
    assert session_id == "sess-a"
    assert last_message_time == 42.5
