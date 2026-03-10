"""Tests for app-level session helpers."""

import queue
from types import SimpleNamespace

import cc_dump.app.domain_store
import cc_dump.app.view_store
import cc_dump.tui.app
import cc_dump.tui.event_handlers
from cc_dump.pipeline.event_types import RequestHeadersEvent
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


def test_handle_event_inner_uses_view_store_only_for_active_session(monkeypatch):
    app = _make_app()
    event = RequestHeadersEvent(headers={}, request_id="")
    captured: dict[str, object] = {}

    def fake_handler(event_obj, state_obj, widgets_obj, app_state_obj, log_fn):
        _ = (event_obj, state_obj, app_state_obj, log_fn)
        captured["view_store"] = widgets_obj.get("view_store")
        return app._app_state

    monkeypatch.setitem(cc_dump.tui.event_handlers.EVENT_HANDLERS, event.kind, fake_handler)
    monkeypatch.setattr(cc_dump.tui.app.stx, "is_safe", lambda _app: True)
    monkeypatch.setattr(app, "_resolve_event_provider", lambda _event: "anthropic")
    monkeypatch.setattr(
        app,
        "_resolve_event_session_key",
        lambda _event, provider=None: "session-other",
    )
    monkeypatch.setattr(app, "_active_session_key_from_tabs", lambda: "session-active")
    monkeypatch.setattr(app, "_get_conv", lambda session_key=None: object())
    monkeypatch.setattr(app, "_get_domain_store", lambda session_key=None: object())
    monkeypatch.setattr(app, "_track_request_activity", lambda _request_id: None)
    monkeypatch.setattr(app, "_sync_detected_session", lambda _state: None)

    app._handle_event_inner(event)

    assert captured["view_store"] is None


def test_handle_event_inner_passes_view_store_for_active_session(monkeypatch):
    app = _make_app()
    event = RequestHeadersEvent(headers={}, request_id="")
    captured: dict[str, object] = {}

    def fake_handler(event_obj, state_obj, widgets_obj, app_state_obj, log_fn):
        _ = (event_obj, state_obj, app_state_obj, log_fn)
        captured["view_store"] = widgets_obj.get("view_store")
        return app._app_state

    monkeypatch.setitem(cc_dump.tui.event_handlers.EVENT_HANDLERS, event.kind, fake_handler)
    monkeypatch.setattr(cc_dump.tui.app.stx, "is_safe", lambda _app: True)
    monkeypatch.setattr(cc_dump.tui.app.CcDumpApp, "active_filters", property(lambda self: {}))
    monkeypatch.setattr(app, "_resolve_event_provider", lambda _event: "anthropic")
    monkeypatch.setattr(
        app,
        "_resolve_event_session_key",
        lambda _event, provider=None: "session-active",
    )
    monkeypatch.setattr(app, "_active_session_key_from_tabs", lambda: "session-active")
    monkeypatch.setattr(app, "_get_conv", lambda session_key=None: object())
    monkeypatch.setattr(app, "_get_domain_store", lambda session_key=None: object())
    monkeypatch.setattr(app, "_track_request_activity", lambda _request_id: None)
    monkeypatch.setattr(app, "_sync_detected_session", lambda _state: None)

    app._handle_event_inner(event)

    assert captured["view_store"] is app._view_store
