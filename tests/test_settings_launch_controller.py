from types import SimpleNamespace

import cc_dump.tui.settings_launch_controller as settings_launch
from cc_dump.app.tmux_controller import LaunchAction, LaunchResult


class _ViewStore:
    def __init__(self):
        self.last_update: dict[str, str] | None = None

    def update(self, values: dict[str, str]) -> None:
        self.last_update = values


class _App:
    def __init__(self, tmux):
        self._tmux_controller = tmux
        self._provider_endpoints: dict[str, object] = {}
        self._view_store = _ViewStore()
        self.notifications: list[str] = []

    def _active_resume_session_id(self) -> str:
        return ""

    def _app_log(self, _level: str, _message: str) -> None:
        return

    def notify(self, message, severity=None) -> None:  # pragma: no cover - severity unused
        self.notifications.append(str(message))

    def _sync_tmux_to_store(self) -> None:
        return


class _Tmux:
    def __init__(self, result: LaunchResult):
        self._result = result

    def configure_launcher(self, **_kwargs) -> None:
        return

    def launch_tool(self, command: str = "") -> LaunchResult:
        return self._result


def _patch_profile(monkeypatch, command: str = "copilot --foo"):
    profile = SimpleNamespace(
        process_names=("copilot",),
        environment={"ANTHROPIC_BASE_URL": "http://127.0.0.1:1234"},
        launcher_label="copilot",
        command=command,
        launcher_key="copilot",
    )
    monkeypatch.setattr(settings_launch.cc_dump.app.launch_config, "option_value", lambda *_a, **_k: False)
    monkeypatch.setattr(
        settings_launch.cc_dump.app.launch_config,
        "build_launch_profile",
        lambda *_a, **_k: profile,
    )


def test_launch_with_config_notifies_exact_executed_command(monkeypatch):
    _patch_profile(monkeypatch)
    shell_command = "ANTHROPIC_BASE_URL=http://127.0.0.1:1234 copilot --foo"
    tmux = _Tmux(
        LaunchResult(
            LaunchAction.LAUNCHED,
            detail="copilot --foo",
            success=True,
            command=shell_command,
        )
    )
    app = _App(tmux)

    settings_launch.launch_with_config(
        app, config=SimpleNamespace(name="copilot", resolved_command="copilot")
    )

    assert app.notifications[-1] == "launched: {}".format(shell_command)


def test_launch_with_config_falls_back_to_detail_when_command_missing(monkeypatch):
    _patch_profile(monkeypatch)
    tmux = _Tmux(
        LaunchResult(
            LaunchAction.FOCUSED,
            detail="existing pane %2",
            success=True,
            command="",
        )
    )
    app = _App(tmux)

    settings_launch.launch_with_config(
        app, config=SimpleNamespace(name="copilot", resolved_command="copilot")
    )

    assert app.notifications[-1] == "focused: existing pane %2"
