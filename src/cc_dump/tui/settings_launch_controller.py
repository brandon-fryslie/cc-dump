"""Settings + launch panel control-plane helpers.

// [LAW:locality-or-seam] Panel-specific orchestration is isolated from app root wiring.
"""

from __future__ import annotations

import cc_dump.app.launch_config
import cc_dump.io.logging_setup
import cc_dump.tui.launch_config_panel
import cc_dump.tui.settings_panel


def open_settings(app) -> None:
    """Open settings panel using persisted defaults from settings store."""
    initial_values = {}
    for field_def in cc_dump.tui.settings_panel.SETTINGS_FIELDS:
        val = app._settings_store.get(field_def.key) if app._settings_store else None
        initial_values[field_def.key] = val if val is not None else field_def.default

    app._view_store.set("panel:settings", True)
    panel = cc_dump.tui.settings_panel.create_settings_panel(initial_values)
    app.screen.mount(panel)


def close_settings(app) -> None:
    """Close settings panel and restore focus to the active conversation."""
    for panel in app.screen.query(cc_dump.tui.settings_panel.SettingsPanel):
        panel.remove()
    app._view_store.set("panel:settings", False)
    conv = app._get_conv()
    if conv is not None:
        conv.focus()


def open_launch_config(app) -> None:
    """Open launch-config panel using persisted launcher profiles."""
    configs = cc_dump.app.launch_config.load_configs()
    active_name = cc_dump.app.launch_config.load_active_name()

    app._view_store.set("panel:launch_config", True)
    panel = cc_dump.tui.launch_config_panel.create_launch_config_panel(
        configs,
        active_name,
    )
    app.screen.mount(panel)


def close_launch_config(app) -> None:
    """Close launch-config panel and restore focus to the active conversation."""
    for panel in app.screen.query(cc_dump.tui.launch_config_panel.LaunchConfigPanel):
        panel.remove()
    app._view_store.set("panel:launch_config", False)
    conv = app._get_conv()
    if conv is not None:
        conv.focus()


def launch_with_config(app, config, *, log_label: str = "launch_with_config") -> None:
    """Build launch profile and execute tool launch via tmux boundary."""
    tmux = app._tmux_controller
    if tmux is None:
        app.notify("Tmux not available", severity="warning")
        return

    session_id = app._active_resume_session_id() if config.auto_resume else ""
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
    if result.success:
        app.notify("{}: {}".format(result.action.value, result.detail))
    else:
        app.notify("Launch failed: {}".format(result.detail), severity="error")
    app._view_store.update(
        {
            "launch:active_name": config.name,
            "launch:active_tool": profile.launcher_key,
        }
    )
    app._sync_tmux_to_store()
