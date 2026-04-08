"""Tests for app-level session helpers."""

import queue
from types import SimpleNamespace

import cc_dump.app.domain_store
import cc_dump.app.view_store
import cc_dump.tui.app
import cc_dump.tui.event_handlers
import cc_dump.tui.session_registry
from cc_dump.pipeline.event_types import RequestHeadersEvent
from cc_dump.core.formatting_impl import ProviderRuntimeState
from cc_dump.tui.app import CcDumpApp


def _make_app():
    state = ProviderRuntimeState()
    return CcDumpApp(
        event_queue=queue.Queue(),
        state=state,
        router=SimpleNamespace(stop=lambda: None),
        view_store=cc_dump.app.view_store.create(),
        domain_store=cc_dump.app.domain_store.DomainStore(),
    )


def _materialize_session(app, key: str):
    """Force a non-default Session into the registry without a tabs widget."""
    session = app._sessions.ensure(key, factory=app._build_session)
    app._sessions.set_active(session.key)
    return session


def test_active_resume_session_id_prefers_active_session_tab(monkeypatch):
    app = _make_app()
    app._providers.default().last_notified_session = "legacy-main"
    _materialize_session(app, "sess-a")

    monkeypatch.setattr(app, "_sync_active_from_tabs", lambda: app._sessions.active())

    assert app._active_resume_session_id() == "sess-a"


def test_get_active_session_panel_state_reads_per_session_last_message(monkeypatch):
    app = _make_app()
    app._providers.default().last_notified_session = "legacy-main"
    session_a = _materialize_session(app, "sess-a")
    app._sessions.default().last_message_time = 11.0
    session_a.last_message_time = 42.5

    monkeypatch.setattr(app, "_sync_active_from_tabs", lambda: app._sessions.active())

    session_id, last_message_time = app._get_active_session_panel_state()
    assert session_id == "sess-a"
    assert last_message_time == 42.5


def _make_fake_session(app, key: str):
    return cc_dump.tui.session_registry.Session(
        key=key,
        tab_id=f"tab-{key}",
        conv_id=f"conv-{key}",
        domain_store=cc_dump.app.domain_store.DomainStore(),
        provider="anthropic",
        is_default=False,
    )


def test_handle_event_inner_uses_view_store_only_for_active_session(monkeypatch):
    import cc_dump.tui.session_registry
    app = _make_app()
    event = RequestHeadersEvent(headers={}, request_id="")
    captured: dict[str, object] = {}

    other = _make_fake_session(app, "session-other")
    active = _make_fake_session(app, "session-active")

    def fake_handler(event_obj, state_obj, context_obj, log_fn):
        _ = (event_obj, state_obj, log_fn)
        captured["view_store"] = context_obj.get("view_store")

    monkeypatch.setitem(cc_dump.tui.event_handlers.EVENT_HANDLERS, event.kind, fake_handler)
    monkeypatch.setattr(cc_dump.tui.app.stx, "is_safe", lambda _app: True)
    monkeypatch.setattr(app, "_resolve_event_provider", lambda _event: "anthropic")
    monkeypatch.setattr(app, "_resolve_event_session", lambda _event, provider=None: other)
    monkeypatch.setattr(app, "_sync_active_from_tabs", lambda: active)
    monkeypatch.setattr(app, "_query_safe", lambda _selector: object())
    monkeypatch.setattr(app, "_track_request_activity", lambda _request_id: None)
    monkeypatch.setattr(app, "_sync_detected_session", lambda _state: None)

    app._handle_event_inner(event)

    assert captured["view_store"] is None


def test_handle_event_inner_passes_view_store_for_active_session(monkeypatch):
    import cc_dump.tui.session_registry
    app = _make_app()
    event = RequestHeadersEvent(headers={}, request_id="")
    captured: dict[str, object] = {}

    active = _make_fake_session(app, "session-active")

    def fake_handler(event_obj, state_obj, context_obj, log_fn):
        _ = (event_obj, state_obj, log_fn)
        captured["view_store"] = context_obj.get("view_store")

    monkeypatch.setitem(cc_dump.tui.event_handlers.EVENT_HANDLERS, event.kind, fake_handler)
    monkeypatch.setattr(cc_dump.tui.app.stx, "is_safe", lambda _app: True)
    monkeypatch.setattr(cc_dump.tui.app.CcDumpApp, "active_filters", property(lambda self: {}))
    monkeypatch.setattr(app, "_resolve_event_provider", lambda _event: "anthropic")
    monkeypatch.setattr(app, "_resolve_event_session", lambda _event, provider=None: active)
    monkeypatch.setattr(app, "_sync_active_from_tabs", lambda: active)
    monkeypatch.setattr(app, "_query_safe", lambda _selector: object())
    monkeypatch.setattr(app, "_track_request_activity", lambda _request_id: None)
    monkeypatch.setattr(app, "_sync_detected_session", lambda _state: None)

    app._handle_event_inner(event)

    assert captured["view_store"] is app._view_store
