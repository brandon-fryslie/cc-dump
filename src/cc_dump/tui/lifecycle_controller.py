"""App lifecycle controller for TUI mount orchestration.

// [LAW:locality-or-seam] Mount flow is isolated so app.py stays composition-only.
// [LAW:dataflow-not-control-flow] Mount executes as a fixed sequence; inputs drive behavior.
"""

from __future__ import annotations

import threading

from cc_dump.io.stderr_tee import get_tee as _get_tee
import cc_dump.providers
import cc_dump.tui.rendering
import cc_dump.tui.view_store_bridge
import snarfx
from snarfx import textual as stx


def on_mount(app) -> None:
    """Run deterministic app startup sequence.

    // [LAW:single-enforcer] App mount side-effects are centralized at one boundary.
    """
    app._bind_view_store_reactions()
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
    cc_dump.tui.rendering.set_theme(app.current_theme)
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
        proxy_url = str(endpoint.get("proxy_url", "") or "")
        if not proxy_url:
            continue
        mode = str(endpoint.get("proxy_mode", spec.proxy_type) or spec.proxy_type).strip().lower()
        app._app_log("INFO", f"{spec.display_name} endpoint ({mode}): {proxy_url}")
        target = str(endpoint.get("target", "") or "")
        if mode == "reverse" and target:
            app._app_log("INFO", f"  Target: {target}")
            app._app_log("INFO", f"  Usage: {spec.base_url_env}={proxy_url} {spec.client_hint}")
            continue
        ca_path = str(endpoint.get("forward_proxy_ca_cert_path", "") or "")
        suffix = f" NODE_EXTRA_CA_CERTS={ca_path}" if ca_path else ""
        app._app_log(
            "INFO",
            f"  Usage: HTTP_PROXY={proxy_url} HTTPS_PROXY={proxy_url}{suffix} {spec.client_hint}",
        )


def _start_workers(app) -> None:
    app.run_worker(app._drain_events, thread=True, exclusive=False)
    app.run_worker(app._start_file_watcher)


def _seed_panel_state(app) -> None:
    app._sync_panel_display(app.active_panel)
    logs = app._get_logs()
    if logs is not None:
        logs.display = app.show_logs
    info = app._get_info()
    if info is not None:
        info.display = app.show_info
        info.update_info(app._build_server_info())


def _wire_reactive_runtime(app) -> None:
    snarfx.set_scheduler(app.call_from_thread)
    if app._tmux_controller is None:
        return
    stx.reaction(
        app,
        lambda: app._tmux_controller.pane_alive.get(),
        lambda _: app._sync_tmux_to_store(),
    )


def _hydrate_footer(app) -> None:
    app._sync_tmux_to_store()
    app._sync_active_launch_config_state()
    if app._resume_ui_state is not None:
        app._apply_resume_ui_state_preload()
    footer = app._get_footer()
    if footer is not None:
        footer.update_display(
            cc_dump.tui.view_store_bridge.enrich_footer_state(
                app._view_store.footer_state.get()
            )
        )
    app._log_memory_snapshot("startup")


def _resume_or_replay(app) -> None:
    if app._replay_data:
        app._process_replay_data()
    if app._resume_ui_state is not None:
        app._apply_resume_ui_state_postload()
