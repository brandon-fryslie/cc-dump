import cc_dump.tui.session_panel
from cc_dump.tui.session_panel import SessionPanel


def test_session_panel_state_round_trip_without_mount():
    panel = SessionPanel()

    panel.refresh_session_state("session-1", 12.5)
    assert panel.get_state() == {
        "session_id": "session-1",
        "last_message_time": 12.5,
    }

    panel.restore_state({"session_id": "session-2", "last_message_time": 20.0})
    assert panel.get_state() == {
        "session_id": "session-2",
        "last_message_time": 20.0,
    }


def test_session_panel_connected_derives_from_last_message_time(monkeypatch):
    panel = SessionPanel()
    panel.refresh_session_state("session-1", 100.0)

    monkeypatch.setattr(cc_dump.tui.session_panel.time, "monotonic", lambda: 150.0)
    assert panel._connected is True

    monkeypatch.setattr(cc_dump.tui.session_panel.time, "monotonic", lambda: 300.0)
    assert panel._connected is False
