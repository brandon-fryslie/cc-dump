from cc_dump.tui.info_panel import InfoPanel


def test_info_panel_reactive_state_round_trip():
    panel = InfoPanel()
    info = {
        "status": "connected",
        "url": "http://localhost:1234",
        "model": "gpt-5",
    }

    panel.update_info(info)
    assert panel.get_state()["info"] == info
    assert panel._rows

    restored = {"status": "idle"}
    panel.restore_state({"info": restored})
    assert panel.get_state()["info"] == restored
