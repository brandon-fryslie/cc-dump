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


def _endpoint_mode(spec, endpoint: dict[str, object]) -> str:
    """Return normalized endpoint mode."""
    raw = endpoint.get("proxy_mode", spec.proxy_type)
    return str(raw or spec.proxy_type).strip().lower()


def _endpoint_usage_line(
    spec,
    *,
    mode: str,
    proxy_url: str,
    target: str,
    ca_path: str,
) -> str:
    """Build provider usage line preserving existing reverse-target behavior."""
    if mode == "reverse" and target:
        return f"  Usage: {spec.base_url_env}={proxy_url} {spec.client_hint}"
    suffix = f" NODE_EXTRA_CA_CERTS={ca_path}" if ca_path else ""
    return (
        f"  Usage: HTTP_PROXY={proxy_url} HTTPS_PROXY={proxy_url}{suffix} "
        f"{spec.client_hint}"
    )


def _endpoint_detail_lines(spec, endpoint: dict[str, object]) -> list[str]:
    """Return detail lines for one provider endpoint."""
    proxy_url = str(endpoint.get("proxy_url", "") or "")
    mode = _endpoint_mode(spec, endpoint)
    target = str(endpoint.get("target", "") or "")
    ca_path = str(endpoint.get("forward_proxy_ca_cert_path", "") or "")
    details = [f"{spec.display_name} endpoint ({mode}): {proxy_url}"]
    if mode == "reverse" and target:
        details.append(f"  Target: {target}")
    details.append(
        _endpoint_usage_line(
            spec,
            mode=mode,
            proxy_url=proxy_url,
            target=target,
            ca_path=ca_path,
        )
    )
    return details


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
        # // [LAW:dataflow-not-control-flow] Endpoint logging is derived line data.
        for line in _endpoint_detail_lines(spec, endpoint):
            app._app_log("INFO", line)


def _start_workers(app) -> None:
    app.run_worker(app._drain_events, thread=True, exclusive=False)
    app.run_worker(app._start_file_watcher)


def _seed_panel_state(app) -> None:
    app._sync_panel_display(app.active_panel)
    app._sync_sidebar_panels(
        (
            bool(app._view_store.get("panel:settings")),
            bool(app._view_store.get("panel:launch_config")),
            bool(app._view_store.get("panel:side_channel")),
        )
    )
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
            return (False, False, False)
        pane_alive = tmux.pane_alive.get() if hasattr(tmux, "pane_alive") else False
        auto_obs = getattr(tmux, "auto_zoom_state", None)
        zoom_obs = getattr(tmux, "zoomed_state", None)
        auto_zoom = auto_obs.get() if auto_obs is not None else bool(getattr(tmux, "auto_zoom", False))
        zoomed = zoom_obs.get() if zoom_obs is not None else bool(getattr(tmux, "_is_zoomed", False))
        return (pane_alive, auto_zoom, zoomed)

    stx.reaction(
        app,
        _tmux_projection,
        lambda _: app._sync_tmux_to_store(),
    )


def _hydrate_footer(app) -> None:
    app._sync_tmux_to_store()
    app._sync_active_launch_config_state()
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
