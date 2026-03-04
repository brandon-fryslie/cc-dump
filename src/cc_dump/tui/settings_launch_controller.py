"""Settings + launch panel control-plane helpers.

// [LAW:locality-or-seam] Panel-specific orchestration is isolated from app root wiring.
"""

from __future__ import annotations

import cc_dump.app.launch_config
import cc_dump.tui.launch_config_panel
import cc_dump.tui.settings_panel


def initial_settings_values(app) -> dict:
    values = {}
    for field_def in cc_dump.tui.settings_panel.SETTINGS_FIELDS:
        val = app._settings_store.get(field_def.key) if app._settings_store else None
        values[field_def.key] = val if val is not None else field_def.default
    return values


def _ensure_settings_panel(app):
    existing = app.screen.query(cc_dump.tui.settings_panel.SettingsPanel)
    if existing:
        return existing.first()
    panel = cc_dump.tui.settings_panel.create_settings_panel(initial_settings_values(app))
    panel.display = False
    app.screen.mount(panel)
    return panel


def _ensure_launch_config_panel(app, configs: list, active_name: str):
    existing = app.screen.query(cc_dump.tui.launch_config_panel.LaunchConfigPanel)
    if existing:
        panel = existing.first()
        panel.reset_configs(configs, active_name)
        return panel
    panel = cc_dump.tui.launch_config_panel.create_launch_config_panel(
        configs,
        active_name,
    )
    panel.display = False
    app.screen.mount(panel)
    return panel


def open_settings(app) -> None:
    """Open settings panel using persisted defaults from settings store."""
    panel = _ensure_settings_panel(app)
    panel.reset_values(initial_settings_values(app))
    app._view_store.update(
        {
            "panel:settings": True,
            "panel:launch_config": False,
            "panel:side_channel": False,
        }
    )


def close_settings(app) -> None:
    """Hide settings panel."""
    app._view_store.set("panel:settings", False)


def open_launch_config(app) -> None:
    """Open launch-config panel using persisted launcher profiles."""
    configs = cc_dump.app.launch_config.load_configs()
    active_name = cc_dump.app.launch_config.load_active_name()
    _ensure_launch_config_panel(app, configs, active_name)
    app._view_store.update(
        {
            "panel:settings": False,
            "panel:launch_config": True,
            "panel:side_channel": False,
        }
    )


def close_launch_config(app) -> None:
    """Hide launch-config panel."""
    app._view_store.set("panel:launch_config", False)


def _resume_session_id(app, config) -> str:
    auto_resume = cc_dump.app.launch_config.option_value(config, "auto_resume")
    return app._active_resume_session_id() if auto_resume else ""


def _notify_launch_result(app, result) -> None:
    if result.success:
        detail = result.command or result.detail
        app.notify("{}: {}".format(result.action.value, detail))
        return
    app.notify("Launch failed: {}".format(result.detail), severity="error")


def launch_with_config(app, config, *, log_label: str = "launch_with_config") -> None:
    """Build launch profile and execute tool launch via tmux boundary."""
    tmux = app._tmux_controller
    if tmux is None:
        app.notify("Tmux not available", severity="warning")
        return

    session_id = _resume_session_id(app, config)
    profile = cc_dump.app.launch_config.build_launch_profile(
        config,
        provider_endpoints=app._provider_endpoints,
        session_id=session_id,
    )
    tmux.configure_launcher(
        command=config.resolved_command,
        process_names=profile.process_names,
        launch_env=profile.environment,
        launcher_label=profile.launcher_label,
    )
    result = tmux.launch_tool(command=profile.command)
    app._app_log("INFO", "{}: {}".format(log_label, result))
    _notify_launch_result(app, result)
    app._view_store.update(
        {
            "launch:active_name": config.name,
            "launch:active_tool": profile.launcher_key,
        }
    )
    app._sync_tmux_to_store()
