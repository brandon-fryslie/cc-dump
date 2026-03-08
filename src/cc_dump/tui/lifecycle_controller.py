"""App lifecycle controller for TUI mount orchestration.

// [LAW:locality-or-seam] Mount flow is isolated so app.py stays composition-only.
// [LAW:dataflow-not-control-flow] Mount executes as a fixed sequence; inputs drive behavior.
"""

from __future__ import annotations

import threading

from cc_dump.io.stderr_tee import get_tee as _get_tee
import cc_dump.providers
import cc_dump.tui.rendering
import snarfx
from snarfx import textual as stx


def on_mount(app) -> None:
    """Run deterministic app startup sequence.

    // [LAW:single-enforcer] App mount side-effects are centralized at one boundary.
    """
    _restore_theme(app)
    _connect_stderr_tee(app)
    _log_proxy_endpoints(app)
    _start_workers(app)
    _seed_panel_state(app)
    _wire_reactive_runtime(app)
    _hydrate_footer(app)
    _resume_or_replay(app)


def _restore_theme(app) -> None:
    saved = app._settings_store.get("theme") if app._settings_store else None
    if saved and saved in app.available_themes:
        app.theme = saved
    cc_dump.tui.rendering.set_theme(app.current_theme, runtime=app._render_runtime)
    app._apply_markdown_theme()


def _connect_stderr_tee(app) -> None:
    tee = _get_tee()
    if tee is None:
        return
    main_thread = threading.current_thread()

    def _drain(level, source, message):
        formatted = f"[{source}] {message}" if source != "stderr" else message
        if threading.current_thread() is main_thread:
            app._app_log(level, formatted, False)
            return
        app.call_from_thread(app._app_log, level, formatted, False)

    tee.connect(_drain)


def _log_proxy_endpoints(app) -> None:
    app._app_log("INFO", "🚀 cc-dump proxy started")
    app._app_log("INFO", f"Listening on: http://{app._host}:{app._port}")
    for spec in cc_dump.providers.all_provider_specs():
        endpoint = app._provider_endpoints.get(spec.key)
        if endpoint is None:
            continue
        if not endpoint.proxy_url:
            continue
        # // [LAW:dataflow-not-control-flow] Endpoint logging is derived line data.
        for line in cc_dump.providers.build_provider_endpoint_detail_lines(endpoint):
            app._app_log("INFO", line)


def _start_workers(app) -> None:
    app.run_worker(app._drain_events, thread=True, exclusive=False)
    app.run_worker(app._start_file_watcher)


def _seed_panel_state(app) -> None:
    app.active_panel = app.active_panel
    info = app._get_info()
    if info is not None:
        info.update_info(app._build_server_info())


def _wire_reactive_runtime(app) -> None:
    snarfx.set_scheduler(app.call_from_thread)
    if app._tmux_controller is None:
        return

    def _tmux_projection():
        tmux = app._tmux_controller
        if tmux is None:
            return False
        pane_alive = tmux.pane_alive.get() if hasattr(tmux, "pane_alive") else False
        return pane_alive

    stx.reaction(
        app,
        _tmux_projection,
        lambda _: app._sync_tmux_to_store(),
    )


def _hydrate_footer(app) -> None:
    app._sync_tmux_to_store()
    app._sync_active_launch_config_state()
    app._log_memory_snapshot("startup")


def _resume_or_replay(app) -> None:
    if app._replay_data:
        app._process_replay_data()
