"""Tests for UI state sidecar persistence helpers."""

from cc_dump.session_sidecar import (
    sidecar_path_for_har,
    save_ui_state,
    load_ui_state,
)


def test_sidecar_path_for_har():
    assert sidecar_path_for_har("/tmp/recording-1.har") == "/tmp/recording-1.har.ui.json"


def test_save_and_load_ui_state_roundtrip(tmp_path):
    har_path = tmp_path / "recording.har"
    har_path.write_text("{}", encoding="utf-8")
    ui_state = {"view_store": {"panel:active": "stats"}, "conv": {"follow_state": "active"}}

    sidecar_path = save_ui_state(str(har_path), ui_state)
    loaded = load_ui_state(str(har_path))

    assert sidecar_path.endswith(".ui.json")
    assert loaded is not None
    assert loaded["version"] == 1
    assert loaded["ui_state"] == ui_state


def test_load_ui_state_missing_or_invalid_returns_none(tmp_path):
    har_path = tmp_path / "missing.har"
    assert load_ui_state(str(har_path)) is None

    sidecar = tmp_path / "bad.har.ui.json"
    sidecar.write_text("{not json", encoding="utf-8")
    assert load_ui_state(str(tmp_path / "bad.har")) is None


def test_save_ui_state_handles_cwd_relative_har_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    har_path = "recording.har"
    (tmp_path / har_path).write_text("{}", encoding="utf-8")
    ui_state = {"view_store": {"panel:active": "stats"}}

    sidecar_path = save_ui_state(har_path, ui_state)
    loaded = load_ui_state(har_path)

    assert sidecar_path == "recording.har.ui.json"
    assert loaded is not None
    assert loaded["ui_state"] == ui_state
