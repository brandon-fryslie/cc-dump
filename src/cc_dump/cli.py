"""CLI entry point for cc-dump."""

import argparse
import hashlib
import http.server
import logging
import os
import queue
import signal
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cc_dump.pipeline.proxy import ProxyHandler, make_handler_class
from cc_dump.pipeline.router import EventRouter, QueueSubscriber, DirectSubscriber
from cc_dump.app.analytics_store import AnalyticsStore
import cc_dump.io.stderr_tee
import cc_dump.core.palette
import cc_dump.io.sessions
import cc_dump.cli_presentation
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
from cc_dump.pipeline.proxy import RequestPipeline
import cc_dump.app.view_store
import cc_dump.app.hot_reload
import cc_dump.app.domain_store
import cc_dump.io.logging_setup
import cc_dump.providers
from cc_dump.tui.app import CcDumpApp

logger = logging.getLogger(__name__)


def _detect_run_subcommand(
    argv: list[str],
) -> tuple[str | None, list[str], list[str]]:
    """Parse 'run' subcommand from argv (without program name).

    Returns (config_name_or_None, cc_dump_flags, tool_extra_args).
    When no 'run' subcommand, returns (None, original_argv, []).

    Usage: cc-dump run <config-name> [cc-dump-flags...] [-- tool-extra-args...]
    """
    if not argv or argv[0] != "run":
        return None, argv, []
    rest = argv[1:]
    if not rest or rest[0] in ("-h", "--help"):
        print(
            "Usage: cc-dump run <config-name> [cc-dump-flags...] [-- tool-extra-args...]"
            "\n\nStart cc-dump and immediately auto-launch the named config."
            "\nLaunch settings come from the saved launch config."
            "\nArguments after '--' are appended to the config's extra args."
            "\n\nExamples:"
            "\n  cc-dump run claude"
            "\n  cc-dump run claude --port 5000"
            "\n  cc-dump run claude -- --dangerously-bypass-permissions"
            "\n  cc-dump run haiku --port 5000 -- --continue"
        )
        sys.exit(0)
    config_name = rest[0]
    remaining = rest[1:]
    separator_idx = remaining.index("--") if "--" in remaining else len(remaining)
    cc_dump_flags = remaining[:separator_idx]
    tool_extra_args = remaining[separator_idx + 1 :] if separator_idx < len(remaining) else []
    return config_name, cc_dump_flags, tool_extra_args


def _resolve_auto_launch_config_name(config_name: str | None) -> str | None:
    """Validate requested run config before booting the app."""
    if config_name is None:
        return None
    configs = cc_dump.app.launch_config.load_configs()
    by_name = {c.name: c for c in configs}
    if config_name in by_name:
        return config_name
    available = ", ".join(c.name for c in configs)
    print(
        "Error: unknown launch config '{}'. Available: {}".format(config_name, available),
        file=sys.stderr,
    )
    sys.exit(2)


def _recordings_output_dir(record_arg: str | None) -> Path:
    default_dir = Path(os.path.expanduser("~/.local/share/cc-dump/recordings"))
    if not record_arg:
        return default_dir
    candidate = Path(os.path.expanduser(record_arg))
    if candidate.exists() and candidate.is_dir():
        return candidate
    # [LAW:dataflow-not-control-flow] Legacy file-like input maps to its parent directory.
    return candidate.parent if candidate.suffix.lower() == ".har" else candidate


def _short_recording_hash(provider: str, timestamp: str) -> str:
    payload = f"{provider}:{timestamp}:{os.getpid()}:{uuid.uuid4().hex}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _recording_path_for_provider(recordings_dir: Path, provider: str, timestamp: str) -> str:
    # [LAW:one-source-of-truth] HAR filename is derived from provider + timestamp + short hash.
    filename = f"ccdump-{provider}-{timestamp}-{_short_recording_hash(provider, timestamp)}.har"
    return str(recordings_dir / filename)


@dataclass(frozen=True)
class ProviderProxyBinding:
    """Runtime proxy binding for one provider.

    // [LAW:one-type-per-behavior] One binding type owns server, handler, and endpoint state.
    """

    spec: cc_dump.providers.ProviderSpec
    server: http.server.ThreadingHTTPServer
    handler_class: type[ProxyHandler]
    port: int
    endpoint: cc_dump.providers.ProviderEndpoint


@dataclass(frozen=True)
class ProxyRuntime:
    """Runtime-owned provider bindings and derived state.

    // [LAW:one-source-of-truth] Active provider topology is owned by one value.
    """

    bindings: tuple[ProviderProxyBinding, ...]
    provider_endpoints: cc_dump.providers.ProviderEndpointMap
    provider_states: dict[str, "ProviderRuntimeState"]


ProviderRuntimeState = cc_dump.core.formatting_impl.ProviderRuntimeState


def _new_provider_state() -> ProviderRuntimeState:
    return ProviderRuntimeState()


def _active_provider_specs(
    args: argparse.Namespace,
    default_provider_spec: cc_dump.providers.ProviderSpec,
) -> tuple[cc_dump.providers.ProviderSpec, ...]:
    optional_specs = tuple(
        spec
        for spec in cc_dump.providers.optional_proxy_provider_specs()
        if not getattr(args, f"no_{spec.key}")
    )
    return (default_provider_spec, *optional_specs)


def _create_forward_proxy_ca(
    args: argparse.Namespace,
    active_specs: tuple[cc_dump.providers.ProviderSpec, ...],
):
    has_forward_proxy = any(spec.proxy_type == "forward" for spec in active_specs)
    if not has_forward_proxy:
        return None
    from cc_dump.pipeline.forward_proxy_tls import ForwardProxyCertificateAuthority
    ca_dir = Path(args.forward_proxy_ca_dir) if args.forward_proxy_ca_dir else None
    return ForwardProxyCertificateAuthority(ca_dir=ca_dir)


def _provider_bind_port(
    args: argparse.Namespace,
    spec: cc_dump.providers.ProviderSpec,
) -> int:
    attr_name = "port" if spec.key == cc_dump.providers.DEFAULT_PROVIDER_KEY else f"{spec.key}_port"
    return int(getattr(args, attr_name))


def _provider_target(
    args: argparse.Namespace,
    spec: cc_dump.providers.ProviderSpec,
) -> str:
    attr_name = "target" if spec.key == cc_dump.providers.DEFAULT_PROVIDER_KEY else f"{spec.key}_target"
    raw_target = str(getattr(args, attr_name))
    return raw_target.rstrip("/") if spec.proxy_type == "reverse" else ""


def _start_proxy_server(host, port, handler_class):
    """Create and start an HTTP proxy server. Returns (server, actual_port, thread)."""
    srv = http.server.ThreadingHTTPServer((host, port), handler_class)
    ap = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, ap, t


def _start_provider_binding(
    *,
    args: argparse.Namespace,
    spec: cc_dump.providers.ProviderSpec,
    event_q: queue.Queue[PipelineEvent],
    forward_proxy_ca,
) -> ProviderProxyBinding:
    provider_target = _provider_target(args, spec)
    provider_ca = forward_proxy_ca if spec.proxy_type == "forward" else None
    handler = make_handler_class(
        provider=spec.key,
        target_host=provider_target if spec.proxy_type == "reverse" else None,
        event_queue=event_q,
        forward_proxy_ca=provider_ca,
    )
    server, port, _thread = _start_proxy_server(
        args.host,
        _provider_bind_port(args, spec),
        handler,
    )
    endpoint = cc_dump.providers.build_provider_endpoint(
        spec.key,
        proxy_url=f"http://{args.host}:{port}",
        target=provider_target,
        proxy_mode=spec.proxy_type,
        forward_proxy_ca_cert_path=(
            str(provider_ca.ca_cert_path) if provider_ca is not None else ""
        ),
    )
    return ProviderProxyBinding(
        spec=spec,
        server=server,
        handler_class=handler,
        port=port,
        endpoint=endpoint,
    )


def _build_proxy_runtime(
    *,
    args: argparse.Namespace,
    default_provider_spec: cc_dump.providers.ProviderSpec,
    event_q: queue.Queue[PipelineEvent],
) -> ProxyRuntime:
    active_specs = _active_provider_specs(args, default_provider_spec)
    forward_proxy_ca = _create_forward_proxy_ca(args, active_specs)
    # [LAW:dataflow-not-control-flow] Binding order is fixed; variability lives in active_specs.
    bindings = tuple(
        _start_provider_binding(
            args=args,
            spec=spec,
            event_q=event_q,
            forward_proxy_ca=forward_proxy_ca,
        )
        for spec in active_specs
    )
    return ProxyRuntime(
        bindings=bindings,
        provider_endpoints={binding.spec.key: binding.endpoint for binding in bindings},
        provider_states={binding.spec.key: _new_provider_state() for binding in bindings},
    )


def _configure_side_channel_runtime(
    *,
    settings_store,
    analytics_store: AnalyticsStore,
    base_url: str,
) -> tuple[cc_dump.ai.side_channel.SideChannelManager, cc_dump.ai.data_dispatcher.DataDispatcher]:
    side_channel_mgr = cc_dump.ai.side_channel.SideChannelManager()
    side_channel_mgr.enabled = bool(settings_store.get("side_channel_enabled"))
    side_channel_mgr.set_base_url(base_url)
    side_channel_mgr.set_usage_provider(
        lambda purpose: dict(analytics_store.get_side_channel_purpose_summary().get(purpose, {}))
    )
    return side_channel_mgr, cc_dump.ai.data_dispatcher.DataDispatcher(side_channel_mgr)


def _base_store_context(
    *,
    side_channel_manager,
    tmux_controller,
    settings_store,
    view_store,
) -> dict[str, object]:
    return {
        "side_channel_manager": side_channel_manager,
        "tmux_controller": tmux_controller,
        "settings_store": settings_store,
        "view_store": view_store,
    }


def _app_store_context(base_context: dict[str, object], app: CcDumpApp) -> dict[str, object]:
    return {
        **base_context,
        "app": app,
    }


def _shutdown_binding(binding: ProviderProxyBinding, *, timeout: float) -> None:
    shutdown_thread = threading.Thread(target=binding.server.shutdown, daemon=True)
    shutdown_thread.start()
    try:
        shutdown_thread.join(timeout=timeout)
    except KeyboardInterrupt:
        pass
    if shutdown_thread.is_alive():
        logger.warning("Timeout during shutdown for %s - forcing close", binding.spec.key)
    binding.server.server_close()


def _existing_path(path: str | None) -> str | None:
    return path if path and os.path.exists(path) else None


def _resume_path(primary_record_path: str | None, replay_path: str | None) -> str | None:
    return _existing_path(primary_record_path) or _existing_path(replay_path)


def _build_cli_parser(
    default_provider_spec: cc_dump.providers.ProviderSpec,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude Code API monitor proxy",
        epilog=(
            "Subcommands:\n"
            "  run <config-name> [-- tool-args...]  Start cc-dump and auto-launch a saved launch config"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    target = os.environ.get(
        default_provider_spec.base_url_env,
        default_provider_spec.default_target,
    )
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
        help=(
            "Upstream API URL for reverse proxy mode "
            f"(default: {default_provider_spec.default_target})"
        ),
    )
    parser.add_argument(
        "--record", type=str, default=None, help="HAR recording output directory"
    )
    parser.add_argument(
        "--no-record", action="store_true", help="Disable HAR recording"
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
        help="Replay latest recording. Optional path; defaults to latest recording.",
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
        help="Delete older recordings, keeping newest N (default: 20), and exit.",
    )
    parser.add_argument(
        "--cleanup-dry-run",
        action="store_true",
        default=False,
        help="Preview recording cleanup without deleting files.",
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
    return parser


def _handle_recording_admin_commands(args: argparse.Namespace) -> bool:
    """Handle one-shot recording admin commands.

    Returns True when a command was handled and startup should exit.
    """
    if args.list_recordings:
        recordings = cc_dump.io.sessions.list_recordings()
        # [LAW:single-enforcer] CLI owns terminal side effects; renderer stays pure.
        print(cc_dump.cli_presentation.render_recordings_list(recordings), end="")
        return True

    if args.cleanup_recordings is None:
        return False
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
    return True


def _apply_resume_argument(args: argparse.Namespace) -> bool:
    if args.resume is None:
        return True
    if args.resume == "latest":
        latest = cc_dump.io.sessions.get_latest_recording()
        if latest is None:
            print("No recordings found to resume from.")
            return False
        args.replay = latest
    else:
        args.replay = args.resume
    print(f"🔄 Resuming from: {args.replay}")
    return True


def _apply_continue_argument(args: argparse.Namespace) -> bool:
    if not args.continue_session:
        return True
    latest = cc_dump.io.sessions.get_latest_recording()
    if latest is None:
        print("No recordings found to continue from.")
        return False
    args.replay = latest
    print(f"🔄 Continuing from: {latest}")
    return True


ReplayData = list[tuple[dict, dict, int, dict, dict, str]]


def _load_replay_data(replay_path: str | None) -> tuple[ReplayData | None, bool]:
    if not replay_path:
        return None, True
    print(f"   Loading replay: {replay_path}")
    try:
        replay_data = cc_dump.pipeline.har_replayer.load_har(replay_path)
    except Exception as exc:
        print(f"   Error loading HAR file: {exc}")
        return None, False
    print(f"   Found {len(replay_data)} request/response pairs")
    return replay_data, True


def _configure_har_recording_subscribers(
    *,
    args: argparse.Namespace,
    router: EventRouter,
    bindings: tuple[ProviderProxyBinding, ...],
) -> tuple[list[cc_dump.pipeline.har_recorder.HARRecordingSubscriber], str | None]:
    har_recorders: list[cc_dump.pipeline.har_recorder.HARRecordingSubscriber] = []
    recording_paths: dict[str, str] = {}
    if args.no_record:
        print("   Recording: disabled (--no-record)")
        return har_recorders, None

    # [LAW:one-source-of-truth] Recording output directory is centralized in one resolver.
    recordings_dir = _recordings_output_dir(args.record)
    recordings_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    active_providers = [binding.spec.key for binding in bindings]

    for provider in active_providers:
        record_path = _recording_path_for_provider(recordings_dir, provider, timestamp)
        recording_paths[provider] = record_path
        recorder = cc_dump.pipeline.har_recorder.HARRecordingSubscriber(
            record_path,
            provider_filter=provider,
        )
        har_recorders.append(recorder)
        router.add_subscriber(DirectSubscriber(recorder.on_event))
        print(f"   Recording ({provider}): {record_path} (created on first API call)")
    primary_record_path = next(
        (
            recording_paths.get(binding.spec.key)
            for binding in bindings
            if recording_paths.get(binding.spec.key)
        ),
        None,
    )
    return har_recorders, primary_record_path


def _build_tmux_controller(provider_endpoints):
    tmux_ctrl = None
    active_launcher_label = "tool"
    tmux_state_cls = cc_dump.app.tmux_controller.TmuxState
    if cc_dump.app.tmux_controller.is_available():
        active_config = cc_dump.app.launch_config.get_active_config()
        active_profile = cc_dump.app.launch_config.build_launch_profile(
            active_config,
            provider_endpoints=provider_endpoints,
        )
        active_launcher_label = active_profile.launcher_label.lower()
        tmux_ctrl = cc_dump.app.tmux_controller.TmuxController(
            launch_command=active_config.resolved_command,
            process_names=active_profile.process_names,
            launch_env=active_profile.environment,
            launcher_label=active_profile.launcher_label,
        )
    return tmux_ctrl, active_launcher_label, tmux_state_cls


def _tmux_status_message(tmux_ctrl, tmux_state_cls, active_launcher_label: str) -> str:
    # [LAW:dataflow-not-control-flow] Status message comes from a state map.
    status_map = {
        None: "disabled (not in tmux)" if not os.environ.get("TMUX") else "disabled (libtmux not installed)",
        tmux_state_cls.READY: f"enabled (press 'c' to launch {active_launcher_label})",
        tmux_state_cls.TOOL_RUNNING: f"enabled ({active_launcher_label} running)",
        tmux_state_cls.NOT_IN_TMUX: "disabled (not in tmux)",
        tmux_state_cls.NO_LIBTMUX: "disabled (libtmux not installed)",
    }
    tmux_state = tmux_ctrl.state if tmux_ctrl else None
    return status_map[tmux_state]


def _shutdown_runtime(
    *,
    app: CcDumpApp,
    tmux_ctrl,
    bindings: tuple[ProviderProxyBinding, ...],
    router: EventRouter,
    har_recorders: list[cc_dump.pipeline.har_recorder.HARRecordingSubscriber],
    actual_port: int,
    primary_record_path: str | None,
    replay_arg: str | None,
) -> None:
    # Dump buffered errors to stderr (TUI is gone, terminal is restored)
    if app._error_log:
        logger.error("[cc-dump] Errors during session:")
        for line in app._error_log:
            logger.error("  %s", line)

    # Clean up tmux state (unzoom)
    if tmux_ctrl:
        tmux_ctrl.cleanup()
    # Graceful shutdown with timeout for in-flight requests
    if bindings:
        logger.info("Shutting down gracefully (press Ctrl+C again to force quit)...")
    for binding in bindings:
        _shutdown_binding(binding, timeout=3.0)

    # Clean up other resources
    router.stop()
    for recorder in har_recorders:
        recorder.close()

    # Print restart command — unstoppable (mask SIGINT so Ctrl+C can't suppress it)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    replay_path = _resume_path(primary_record_path, replay_arg)
    cmd = f"{sys.argv[0]} --port {actual_port}"
    if replay_path:
        cmd += f" --resume {replay_path}"
    logger.info("To resume: %s", cmd)
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def main():
    auto_launch_config, _argv, auto_launch_extra_args = _detect_run_subcommand(sys.argv[1:])

    default_provider_key = cc_dump.providers.DEFAULT_PROVIDER_KEY
    default_provider_spec = cc_dump.providers.get_provider_spec(default_provider_key)
    parser = _build_cli_parser(default_provider_spec)
    args = parser.parse_args(_argv)
    auto_launch_config = _resolve_auto_launch_config_name(auto_launch_config)

    # Install stderr tee before anything else writes to stderr
    cc_dump.io.stderr_tee.install()
    # [LAW:single-enforcer] Runtime logger configuration is centralized in io.logging_setup.
    log_runtime = cc_dump.io.logging_setup.configure()
    logger.info(
        "logging configured level=%s file=%s",
        log_runtime.level_name,
        log_runtime.file_path,
    )

    # Initialize color palette before anything else imports it
    cc_dump.core.palette.init_palette()

    if _handle_recording_admin_commands(args):
        return

    if not _apply_resume_argument(args):
        return
    if not _apply_continue_argument(args):
        return

    event_q: queue.Queue[PipelineEvent] = queue.Queue()
    replay_data, replay_ok = _load_replay_data(args.replay)
    if not replay_ok:
        return

    # ─── Start proxy servers ────────────────────────────────────────────────
    # // [LAW:one-type-per-behavior] All providers share ProxyHandler, parameterized by factory.
    proxy_runtime = _build_proxy_runtime(
        args=args,
        default_provider_spec=default_provider_spec,
        event_q=event_q,
    )
    bindings = proxy_runtime.bindings
    provider_endpoints = proxy_runtime.provider_endpoints
    provider_states = proxy_runtime.provider_states
    default_binding = bindings[0]
    actual_port = default_binding.port
    default_target = default_binding.endpoint.target

    print("🚀 cc-dump proxy started")
    for binding in bindings:
        endpoint = binding.endpoint
        for line in cc_dump.providers.build_provider_endpoint_detail_lines(endpoint):
            print(f"   {line}")
    # [LAW:one-source-of-truth] Default-state alias points at canonical per-provider state.
    state = provider_states[default_provider_key]

    # Set up event router with subscribers
    router = EventRouter(event_q)

    # Analytics store (direct subscriber, in-memory)
    # [LAW:single-enforcer] Analytics projection updates before UI queue fan-out to avoid races.
    analytics_store = AnalyticsStore()
    router.add_subscriber(DirectSubscriber(analytics_store.on_event))

    # Display subscriber (queue-based for async consumption)
    display_sub = QueueSubscriber()
    router.add_subscriber(display_sub)

    # HAR recording subscriber (direct subscriber, inline writes)
    har_recorders, primary_record_path = _configure_har_recording_subscribers(
        args=args,
        router=router,
        bindings=bindings,
    )

    # Tmux integration (optional — no-op when not in tmux or libtmux missing)
    # Create settings store (reactive, hot-reloadable)
    settings_store = cc_dump.app.settings_store.create()

    tmux_ctrl, active_launcher_label, tmux_state_cls = _build_tmux_controller(provider_endpoints)
    print(f"   Tmux: {_tmux_status_message(tmux_ctrl, tmux_state_cls, active_launcher_label)}")

    side_channel_mgr, data_dispatcher = _configure_side_channel_runtime(
        settings_store=settings_store,
        analytics_store=analytics_store,
        base_url=default_binding.endpoint.proxy_url,
    )

    # Request pipeline — transforms + interceptors run before forwarding
    pipeline = RequestPipeline(
        transforms=[
            lambda body, url: (cc_dump.ai.side_channel_marker.strip_marker_from_body(body), url),
        ],
        interceptors=[cc_dump.pipeline.sentinel.make_interceptor(tmux_ctrl)],
    )
    # // [LAW:single-enforcer] One shared request pipeline is applied at every provider handler boundary.
    for binding in bindings:
        binding.handler_class.request_pipeline = pipeline

    router.start()

    # Create view store (reactive, hot-reloadable)
    view_store = cc_dump.app.view_store.create()

    # Create domain store (owns FormattedBlock trees, persists across hot-reload)
    domain_store = cc_dump.app.domain_store.DomainStore()

    # Wire settings store reactions (after all consumers are created)
    store_context = _base_store_context(
        side_channel_manager=side_channel_mgr,
        tmux_controller=tmux_ctrl,
        settings_store=settings_store,
        view_store=view_store,
    )
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
        router=router,
        provider_states=provider_states,
        analytics_store=analytics_store,
        host=args.host,
        port=actual_port,
        target=default_target,
        replay_data=replay_data,
        recording_path=primary_record_path,
        replay_file=args.replay,
        tmux_controller=tmux_ctrl,
        side_channel_manager=side_channel_mgr,
        data_dispatcher=data_dispatcher,
        settings_store=settings_store,
        view_store=view_store,
        domain_store=domain_store,
        store_context=store_context,
        provider_endpoints=provider_endpoints,
        auto_launch_config=auto_launch_config,
        auto_launch_extra_args=auto_launch_extra_args,
    )

    app._store_context = _app_store_context(store_context, app)
    try:
        app.run()
    finally:
        _shutdown_runtime(
            app=app,
            tmux_ctrl=tmux_ctrl,
            bindings=bindings,
            router=router,
            har_recorders=har_recorders,
            actual_port=actual_port,
            primary_record_path=primary_record_path,
            replay_arg=args.replay,
        )
