"""CLI entry point for cc-dump."""

import argparse
import http.server
import logging
import os
import queue
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path

from cc_dump.pipeline.proxy import make_handler_class
from cc_dump.pipeline.router import EventRouter, QueueSubscriber, DirectSubscriber
from cc_dump.app.analytics_store import AnalyticsStore
import cc_dump.io.stderr_tee
import cc_dump.core.palette
import cc_dump.io.sessions
from cc_dump.pipeline.event_types import PipelineEvent
import cc_dump.pipeline.har_replayer
import cc_dump.pipeline.har_recorder
import cc_dump.io.settings
import cc_dump.app.tmux_controller
import cc_dump.app.settings_store
import cc_dump.app.launch_config
import cc_dump.ai.side_channel
import cc_dump.ai.data_dispatcher
import cc_dump.pipeline.sentinel
import cc_dump.ai.side_channel_marker
import cc_dump.io.session_sidecar
from cc_dump.pipeline.proxy import RequestPipeline
import cc_dump.app.view_store
import cc_dump.app.hot_reload
import cc_dump.app.domain_store
import cc_dump.tui.view_store_bridge
import cc_dump.io.logging_setup
import cc_dump.providers
from cc_dump.tui.app import CcDumpApp

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Claude Code API monitor proxy")
    target = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument("--port", type=int, default=0, help="Bind port (default: 0, OS-assigned)")
    parser.add_argument(
        "--target",
        type=str,
        default=target,
        help="Upstream API URL for reverse proxy mode (default: https://api.anthropic.com)",
    )
    parser.add_argument(
        "--record", type=str, default=None, help="HAR recording output path"
    )
    parser.add_argument(
        "--no-record", action="store_true", help="Disable HAR recording"
    )
    parser.add_argument(
        "--session",
        type=str,
        default="unnamed-session",
        help="Session name for organizing recordings (default: unnamed-session)",
    )
    parser.add_argument(
        "--replay",
        type=str,
        default=None,
        help="Replay a recorded session (path to .har file)",
    )
    parser.add_argument(
        "--continue",
        dest="continue_session",
        action="store_true",
        default=False,
        help="Continue from most recent recording (replay + live proxy)",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="latest",
        default=None,
        help="Resume UI state sidecar. Optional path; defaults to latest recording.",
    )
    parser.add_argument(
        "--list-recordings",
        action="store_true",
        default=False,
        help="List known HAR recordings and exit.",
    )
    parser.add_argument(
        "--cleanup-recordings",
        nargs="?",
        const=20,
        type=int,
        default=None,
        help="Delete older recordings, keeping newest N (default: 20).",
    )
    parser.add_argument(
        "--cleanup-dry-run",
        action="store_true",
        default=False,
        help="Preview recording cleanup without deleting files.",
    )
    parser.add_argument(
        "--seed-hue",
        type=float,
        default=None,
        help="Seed hue (0-360) for color palette (default: 190, cyan). Env: CC_DUMP_SEED_HUE",
    )
    parser.add_argument(
        "--forward-proxy-ca-dir",
        type=str,
        default=None,
        help="Directory for forward proxy CA key/cert (default: ~/.cc-dump/forward-proxy-ca/)",
    )
    for spec in cc_dump.providers.optional_proxy_provider_specs():
        parser.add_argument(
            f"--{spec.key}-port",
            type=int,
            default=0,
            help=f"Bind port for {spec.display_name} proxy (default: 0, OS-assigned)",
        )
        parser.add_argument(
            f"--{spec.key}-target",
            type=str,
            default=(
                os.environ.get(spec.base_url_env, spec.default_target)
                if spec.proxy_type == "reverse"
                else spec.default_target
            ),
            help=(
                f"Upstream {spec.display_name} API URL (default: {spec.default_target}). "
                f"Env: {spec.base_url_env}"
            ),
        )
        parser.add_argument(
            f"--no-{spec.key}",
            action="store_true",
            default=False,
            help=f"Disable the {spec.display_name} proxy server",
        )
    args = parser.parse_args()

    # Install stderr tee before anything else writes to stderr
    cc_dump.io.stderr_tee.install()
    # [LAW:single-enforcer] Runtime logger configuration is centralized in io.logging_setup.
    log_runtime = cc_dump.io.logging_setup.configure(session_name=args.session)
    logger.info(
        "logging configured level=%s file=%s",
        log_runtime.level_name,
        log_runtime.file_path,
    )

    # Initialize color palette before anything else imports it
    cc_dump.core.palette.init_palette(args.seed_hue)

    if args.list_recordings:
        recordings = cc_dump.io.sessions.list_recordings()
        cc_dump.io.sessions.print_recordings_list(recordings)
        return

    if args.cleanup_recordings is not None:
        result = cc_dump.io.sessions.cleanup_recordings(
            keep=args.cleanup_recordings,
            dry_run=bool(args.cleanup_dry_run),
        )
        mode = "Dry run" if result["dry_run"] else "Cleanup"
        print(
            f"{mode}: removed {result['removed']} recording(s), "
            f"kept {result['kept']}, freed {cc_dump.io.sessions.format_size(result['bytes_freed'])}"
        )
        if result["removed_paths"]:
            for path in result["removed_paths"]:
                print(f"  - {path}")
        return

    # Resolve --continue / --resume to load latest recording
    if args.resume is not None:
        if args.resume == "latest":
            latest = cc_dump.io.sessions.get_latest_recording()
            if latest is None:
                print("No recordings found to resume from.")
                return
            args.replay = latest
        else:
            args.replay = args.resume
        print(f"🔄 Resuming from: {args.replay}")

    if args.continue_session:
        latest = cc_dump.io.sessions.get_latest_recording()
        if latest is None:
            print("No recordings found to continue from.")
            return
        args.replay = latest
        print(f"🔄 Continuing from: {latest}")

    event_q: queue.Queue[PipelineEvent] = queue.Queue()

    # Load replay data if specified, but always start proxy
    server = None
    replay_data = None

    resume_ui_state = None
    if args.replay:
        # Load HAR file (complete messages, NO event conversion)
        print(f"   Loading replay: {args.replay}")

        try:
            replay_data = cc_dump.pipeline.har_replayer.load_har(args.replay)
            print(f"   Found {len(replay_data)} request/response pairs")
            sidecar_payload = cc_dump.io.session_sidecar.load_ui_state(args.replay)
            if isinstance(sidecar_payload, dict):
                loaded_ui = sidecar_payload.get("ui_state", {})
                if isinstance(loaded_ui, dict):
                    resume_ui_state = loaded_ui
                    print(f"   Loaded UI sidecar: {cc_dump.io.session_sidecar.sidecar_path_for_har(args.replay)}")

        except Exception as e:
            print(f"   Error loading HAR file: {e}")
            return

    # ─── Start proxy servers ────────────────────────────────────────────────
    # // [LAW:one-type-per-behavior] All providers share ProxyHandler, parameterized by factory.

    def _start_proxy_server(host, port, handler_class):
        """Create and start an HTTP proxy server. Returns (server, actual_port, thread)."""
        srv = http.server.ThreadingHTTPServer((host, port), handler_class)
        ap = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv, ap, t

    proxy_servers: dict[str, http.server.ThreadingHTTPServer] = {}
    # // [LAW:one-source-of-truth] Handler classes keyed by provider for shared runtime wiring.
    proxy_handlers: dict[str, type[http.server.BaseHTTPRequestHandler]] = {}
    proxy_ports: dict[str, int] = {}
    proxy_targets: dict[str, str | None] = {}
    provider_endpoints: dict[str, dict[str, str]] = {}

    active_specs: list[cc_dump.providers.ProviderSpec] = [
        cc_dump.providers.require_provider_spec(cc_dump.providers.DEFAULT_PROVIDER_KEY)
    ]
    active_specs.extend(
        spec
        for spec in cc_dump.providers.optional_proxy_provider_specs()
        if not getattr(args, f"no_{spec.key}")
    )

    # Forward proxy certificate authority for CONNECT interception.
    forward_proxy_ca = None
    if any(spec.proxy_type == "forward" for spec in active_specs):
        from cc_dump.pipeline.forward_proxy_tls import ForwardProxyCertificateAuthority
        ca_dir = Path(args.forward_proxy_ca_dir) if args.forward_proxy_ca_dir else None
        forward_proxy_ca = ForwardProxyCertificateAuthority(ca_dir=ca_dir)

    for spec in active_specs:
        bind_port = args.port if spec.key == cc_dump.providers.DEFAULT_PROVIDER_KEY else int(getattr(args, f"{spec.key}_port"))
        configured_target = args.target if spec.key == cc_dump.providers.DEFAULT_PROVIDER_KEY else str(getattr(args, f"{spec.key}_target"))
        target_host = configured_target if spec.proxy_type == "reverse" else None
        ca_for_provider = forward_proxy_ca if spec.proxy_type == "forward" else None

        handler = make_handler_class(
            provider=spec.key,
            target_host=target_host,
            event_queue=event_q,
            forward_proxy_ca=ca_for_provider,
        )
        srv, port, _ = _start_proxy_server(args.host, bind_port, handler)
        proxy_servers[spec.key] = srv
        proxy_handlers[spec.key] = handler
        proxy_ports[spec.key] = port
        proxy_targets[spec.key] = configured_target.rstrip("/") if configured_target else None

    actual_port = proxy_ports[cc_dump.providers.DEFAULT_PROVIDER_KEY]
    anthropic_target = proxy_targets.get(cc_dump.providers.DEFAULT_PROVIDER_KEY)
    server = proxy_servers[cc_dump.providers.DEFAULT_PROVIDER_KEY]

    print("🚀 cc-dump proxy started")
    for spec in active_specs:
        proxy_url = f"http://{args.host}:{proxy_ports[spec.key]}"
        target = proxy_targets.get(spec.key, "")
        print(f"   {spec.display_name} endpoint: {proxy_url}")
        print(f"     Proxy type: {spec.proxy_type}")
        if spec.proxy_type == "reverse":
            if target:
                print(f"     Target: {target}")
            print(f"     Usage: {spec.base_url_env}={proxy_url} {spec.client_hint}")
        else:
            print(
                f"     Usage: HTTP_PROXY={proxy_url} HTTPS_PROXY={proxy_url} NODE_EXTRA_CA_CERTS={forward_proxy_ca.ca_cert_path if forward_proxy_ca else ''} {spec.client_hint}"
            )

        provider_endpoints[spec.key] = {
            "proxy_url": proxy_url,
            "target": (target or "") if spec.proxy_type == "reverse" else "",
            "proxy_mode": spec.proxy_type,
        }
        if spec.proxy_type == "forward" and forward_proxy_ca is not None:
            provider_endpoints[spec.key]["forward_proxy_ca_cert_path"] = str(forward_proxy_ca.ca_cert_path)

    # State dict for content tracking (used by formatting layer)
    state = {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
        "current_session": None,  # Track Claude Code session ID for change detection
    }

    # Set up event router with subscribers
    router = EventRouter(event_q)

    # Display subscriber (queue-based for async consumption)
    display_sub = QueueSubscriber()
    router.add_subscriber(display_sub)

    # Analytics store (direct subscriber, in-memory)
    analytics_store = AnalyticsStore()
    router.add_subscriber(DirectSubscriber(analytics_store.on_event))

    # HAR recording subscriber (direct subscriber, inline writes)
    # [LAW:one-source-of-truth] Session name from CLI or default
    session_name = args.session
    har_recorders: list[cc_dump.pipeline.har_recorder.HARRecordingSubscriber] = []
    recording_paths: dict[str, str] = {}
    primary_record_path = None
    if not args.no_record:
        # [LAW:one-source-of-truth] Recordings organized by session name
        record_dir = os.path.expanduser("~/.local/share/cc-dump/recordings")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        active_providers = list(proxy_ports.keys())

        def _recording_path_for_provider(provider: str) -> str:
            # // [LAW:dataflow-not-control-flow] Path is derived from provider + timestamp in one deterministic function.
            if args.record:
                custom = Path(os.path.expanduser(args.record))
                custom_name = custom.name
                if not custom_name.endswith(".har"):
                    custom_name = custom_name + ".har"
                return str(custom.parent / provider / custom_name)
            return os.path.join(record_dir, session_name, provider, f"recording-{timestamp}.har")

        for provider in active_providers:
            record_path = _recording_path_for_provider(provider)
            recording_paths[provider] = record_path
            recorder = cc_dump.pipeline.har_recorder.HARRecordingSubscriber(
                record_path,
                provider_filter=provider,
            )
            har_recorders.append(recorder)
            router.add_subscriber(DirectSubscriber(recorder.on_event))
            print(f"   Recording ({provider}): {record_path} (created on first API call)")
        primary_record_path = recording_paths.get("anthropic") or next(iter(recording_paths.values()), None)
    else:
        print("   Recording: disabled (--no-record)")

    # Tmux integration (optional — no-op when not in tmux or libtmux missing)
    # Create settings store (reactive, hot-reloadable)
    settings_store = cc_dump.app.settings_store.create()

    tmux_ctrl = None
    active_launcher_label = "tool"
    TmuxState = cc_dump.app.tmux_controller.TmuxState
    if cc_dump.app.tmux_controller.is_available():
        active_config = cc_dump.app.launch_config.get_active_config()
        active_profile = cc_dump.app.launch_config.build_launch_profile(
            active_config,
            provider_endpoints=provider_endpoints,
        )
        active_launcher_label = active_profile.launcher_label.lower()
        auto_zoom = bool(settings_store.get("auto_zoom_default"))
        tmux_ctrl = cc_dump.app.tmux_controller.TmuxController(
            launch_command=active_config.resolved_command,
            process_names=active_profile.process_names,
            launch_env=active_profile.environment,
            launcher_label=active_profile.launcher_label,
            auto_zoom=auto_zoom,
        )
        tmux_ctrl.set_port(actual_port)
        # Subscribe for both READY and TOOL_RUNNING (adoption case)
        if tmux_ctrl.state in (TmuxState.READY, TmuxState.TOOL_RUNNING):
            router.add_subscriber(DirectSubscriber(tmux_ctrl.on_event))
    # [LAW:dataflow-not-control-flow] Status message from state, not branching
    _TMUX_STATUS = {
        None: "disabled (not in tmux)" if not os.environ.get("TMUX") else "disabled (libtmux not installed)",
        TmuxState.READY: "enabled (press 'c' to launch {})".format(active_launcher_label),
        TmuxState.TOOL_RUNNING: "enabled ({} running)".format(active_launcher_label),
        TmuxState.NOT_IN_TMUX: "disabled (not in tmux)",
        TmuxState.NO_LIBTMUX: "disabled (libtmux not installed)",
    }
    tmux_state = tmux_ctrl.state if tmux_ctrl else None
    print(f"   Tmux: {_TMUX_STATUS[tmux_state]}")

    # Side channel (AI enrichment via claude -p)
    sc_enabled = bool(settings_store.get("side_channel_enabled"))
    side_channel_mgr = cc_dump.ai.side_channel.SideChannelManager()
    side_channel_mgr.enabled = sc_enabled
    side_channel_mgr.set_base_url(f"http://{args.host}:{actual_port}")

    def _coerce_token_count(value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    def _side_channel_usage_for_purpose(purpose: str) -> dict[str, int]:
        usage_rows = analytics_store.get_side_channel_purpose_summary()
        row = usage_rows.get(purpose)
        if not isinstance(row, dict):
            return {}
        return {
            "input_tokens": _coerce_token_count(row.get("input_tokens", 0)),
            "cache_read_tokens": _coerce_token_count(row.get("cache_read_tokens", 0)),
            "cache_creation_tokens": _coerce_token_count(row.get("cache_creation_tokens", 0)),
            "output_tokens": _coerce_token_count(row.get("output_tokens", 0)),
        }

    side_channel_mgr.set_usage_provider(_side_channel_usage_for_purpose)
    data_dispatcher = cc_dump.ai.data_dispatcher.DataDispatcher(side_channel_mgr)

    # Request pipeline — transforms + interceptors run before forwarding
    pipeline = RequestPipeline(
        transforms=[
            lambda body, url: (cc_dump.ai.side_channel_marker.strip_marker_from_body(body), url),
        ],
        interceptors=[cc_dump.pipeline.sentinel.make_interceptor(tmux_ctrl)],
    )
    # // [LAW:single-enforcer] One shared request pipeline is applied at every provider handler boundary.
    for handler in proxy_handlers.values():
        handler.request_pipeline = pipeline

    router.start()

    # Create view store (reactive, hot-reloadable)
    view_store = cc_dump.app.view_store.create()

    # Create domain store (owns FormattedBlock trees, persists across hot-reload)
    domain_store = cc_dump.app.domain_store.DomainStore()

    # Wire settings store reactions (after all consumers are created)
    store_context = {
        "side_channel_manager": side_channel_mgr,
        "tmux_controller": tmux_ctrl,
        "settings_store": settings_store,
    }
    settings_store._reaction_disposers = cc_dump.app.settings_store.setup_reactions(
        settings_store, store_context
    )

    # Initialize hot-reload watcher
    package_dir = os.path.dirname(os.path.abspath(__file__))
    cc_dump.app.hot_reload.init(package_dir)

    # Launch TUI with database context
    app = CcDumpApp(
        display_sub.queue,
        state,
        router,
        analytics_store=analytics_store,
        session_name=session_name,
        host=args.host,
        port=actual_port,
        target=anthropic_target,
        replay_data=replay_data,
        recording_path=primary_record_path,
        replay_file=args.replay,
        resume_ui_state=resume_ui_state,
        tmux_controller=tmux_ctrl,
        side_channel_manager=side_channel_mgr,
        data_dispatcher=data_dispatcher,
        settings_store=settings_store,
        view_store=view_store,
        domain_store=domain_store,
        store_context=store_context,
        provider_endpoints=provider_endpoints,
    )

    # Store context is finalized here; view-store reactions are bound on app mount.
    store_context["app"] = app
    store_context.update(cc_dump.tui.view_store_bridge.build_reaction_context(app))
    try:
        app.run()
    finally:
        # Dump buffered errors to stderr (TUI is gone, terminal is restored)
        if app._error_log:
            logger.error("[cc-dump] Errors during session:")
            for line in app._error_log:
                logger.error("  %s", line)

        # Clean up tmux state (unzoom)
        if tmux_ctrl:
            tmux_ctrl.cleanup()
        # Graceful shutdown with timeout for in-flight requests
        if server:
            logger.info("Shutting down gracefully (press Ctrl+C again to force quit)...")

            # Try graceful shutdown with 3 second timeout
            shutdown_thread = threading.Thread(target=server.shutdown, daemon=True)
            shutdown_thread.start()
            try:
                shutdown_thread.join(timeout=3.0)
            except KeyboardInterrupt:
                pass  # User forced quit during shutdown

            if shutdown_thread.is_alive():
                # Timeout or interrupted - force close
                logger.warning("Timeout during shutdown - forcing close")
            else:
                # Graceful shutdown succeeded
                logger.info("Server stopped")

            server.server_close()

        # Shutdown optional provider servers
        for provider, srv in proxy_servers.items():
            if provider == "anthropic":
                continue
            shutdown_thread = threading.Thread(target=srv.shutdown, daemon=True)
            shutdown_thread.start()
            try:
                shutdown_thread.join(timeout=2.0)
            except KeyboardInterrupt:
                pass
            srv.server_close()

        # Clean up other resources
        router.stop()
        for recorder in har_recorders:
            recorder.close()

        # Persist UI sidecar next to active HAR (recording path or replay file).
        candidate_record_paths = [
            recording_paths.get("anthropic"),
            *[path for provider, path in recording_paths.items() if provider != "anthropic"],
        ]
        sidecar_target = next(
            (path for path in candidate_record_paths if path and os.path.exists(path)),
            None,
        )
        if sidecar_target is None and args.replay and os.path.exists(args.replay):
            sidecar_target = args.replay
        if sidecar_target:
            try:
                ui_state = app.export_ui_state()
                sidecar_path = cc_dump.io.session_sidecar.save_ui_state(sidecar_target, ui_state)
                logger.info("UI state saved: %s", sidecar_path)
            except Exception as e:
                logger.exception("UI state save failed: %s", e)

        # Print restart command — unstoppable (mask SIGINT so Ctrl+C can't suppress it)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        replay_path = (
            primary_record_path if primary_record_path and os.path.exists(primary_record_path)
            else args.replay if args.replay and os.path.exists(args.replay)
            else None
        )
        cmd = f"{sys.argv[0]} --port {actual_port}"
        if replay_path:
            cmd += f" --resume {replay_path}"
        logger.info("To resume: %s", cmd)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
