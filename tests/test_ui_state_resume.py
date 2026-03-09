"""Tests for app-level session helpers."""

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
    app._app_state["last_message_time_by_session"] = {
        "__default__": 11.0,
        "sess-a": 42.5,
    }

    monkeypatch.setattr(app, "_active_session_key_from_tabs", lambda: "sess-a")

    session_id, last_message_time = app._get_active_session_panel_state()
    assert session_id == "sess-a"
    assert last_message_time == 42.5
