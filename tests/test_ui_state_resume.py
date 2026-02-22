"""Tests for app-level UI state export and resume application."""

import queue
from types import SimpleNamespace

import cc_dump.domain_store
import cc_dump.view_store
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
        view_store=cc_dump.view_store.create(),
        domain_store=cc_dump.domain_store.DomainStore(),
    )


def test_export_ui_state_includes_view_and_app_fields(monkeypatch):
    app = _make_app()
    app.show_logs = True
    app.show_info = False
    app._view_store.set("panel:active", "stats")
    app._view_store.set("search:query", "hello")

    class _Conv:
        def get_state(self):
            return {"follow_state": "active"}

    monkeypatch.setattr(app, "_get_conv", lambda: _Conv())

    exported = app.export_ui_state()
    assert exported["view_store"]["panel:active"] == "stats"
    assert exported["view_store"]["search:query"] == "hello"
    assert exported["app"]["show_logs"] is True
    assert exported["app"]["show_info"] is False
    assert exported["conv"]["follow_state"] == "active"


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

    monkeypatch.setattr(app, "_get_conv", lambda: _Conv())

    app._apply_resume_ui_state_postload()

    assert calls["restore"] == {"foo": "bar"}
    assert calls["rerender"] == 1
