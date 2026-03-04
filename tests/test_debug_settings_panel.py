from types import SimpleNamespace

import cc_dump.tui.debug_settings_panel
from cc_dump.tui.debug_settings_panel import DebugSettingsPanel


def test_memory_toggle_without_app_ref_does_not_change_tracemalloc(monkeypatch):
    starts: list[int] = []
    stops: list[bool] = []

    monkeypatch.setattr(
        cc_dump.tui.debug_settings_panel.cc_dump.io.perf_logging,
        "set_enabled",
        lambda _: None,
    )
    monkeypatch.setattr(cc_dump.tui.debug_settings_panel.tracemalloc, "is_tracing", lambda: False)
    monkeypatch.setattr(
        cc_dump.tui.debug_settings_panel.tracemalloc,
        "start",
        lambda depth: starts.append(depth),
    )
    monkeypatch.setattr(
        cc_dump.tui.debug_settings_panel.tracemalloc,
        "stop",
        lambda: stops.append(True),
    )

    panel = DebugSettingsPanel(app_ref=None)
    panel._apply_toggle_state((True, True))
    panel._apply_toggle_state((True, False))
    panel._toggle_reaction.dispose()

    assert starts == []
    assert stops == []


def test_memory_toggle_with_app_ref_updates_app_and_tracing(monkeypatch):
    starts: list[int] = []
    stops: list[bool] = []
    tracing = {"value": False}

    def _start(depth: int) -> None:
        starts.append(depth)
        tracing["value"] = True

    def _stop() -> None:
        stops.append(True)
        tracing["value"] = False

    monkeypatch.setattr(
        cc_dump.tui.debug_settings_panel.cc_dump.io.perf_logging,
        "set_enabled",
        lambda _: None,
    )
    monkeypatch.setattr(
        cc_dump.tui.debug_settings_panel.tracemalloc,
        "is_tracing",
        lambda: bool(tracing["value"]),
    )
    monkeypatch.setattr(cc_dump.tui.debug_settings_panel.tracemalloc, "start", _start)
    monkeypatch.setattr(cc_dump.tui.debug_settings_panel.tracemalloc, "stop", _stop)

    app_ref = SimpleNamespace(_memory_snapshot_enabled=False)
    panel = DebugSettingsPanel(app_ref=app_ref)
    panel._apply_toggle_state((True, True))
    panel._apply_toggle_state((True, False))
    panel._toggle_reaction.dispose()

    assert app_ref._memory_snapshot_enabled is False
    assert starts == [25]
    assert stops == [True]
