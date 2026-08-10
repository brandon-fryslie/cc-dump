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

import cc_dump.app.domain_store
import cc_dump.app.hot_reload
import cc_dump.app.launch_config
import cc_dump.app.settings_store
import cc_dump.app.tmux_controller
import cc_dump.app.view_store
import cc_dump.cli_presentation
import cc_dump.core.formatting_impl
import cc_dump.core.palette
import cc_dump.io.logging_setup
import cc_dump.io.sessions
import cc_dump.io.settings
import cc_dump.io.stderr_tee
import cc_dump.pipeline.har_recorder
import cc_dump.pipeline.har_replayer
import cc_dump.pipeline.sentinel
import cc_dump.providers
from cc_dump.app.analytics_store import AnalyticsStore
from cc_dump.pipeline.event_types import PipelineEvent
from cc_dump.pipeline.har_replayer import ReplayPair
from cc_dump.pipeline.proxy import ProxyHandler, RequestPipeline, make_handler_class
from cc_dump.pipeline.router import DirectSubscriber, EventRouter, QueueSubscriber
from cc_dump.tui.app import CcDumpApp

logger = logging.getLogger(__name__)


def _detect_run_subcommand(
    argv: list[str],
) -> tuple[str | None, list[str], list[str]]:
    """Parse 'run' subcommand from argv (without program name).

    Returns (config_name_or_None, cc_dump_flags, tool_extra_args).
    When no 'run' subcommand, returns (None, original_argv, []).

    The 'run' token may appear anywhere in argv — flags before and after
    it are collected as cc_dump_flags.  The first positional after 'run'
    is the config name.  Everything after '--' becomes tool_extra_args.

    Usage: cc-dump [flags...] run <config-name> [flags...] [-- tool-extra-args...]
    """
    # // [LAW:dataflow-not-control-flow] Locate 'run' by scanning — no early return for argv[0].
    try:
        run_idx = argv.index("run")
    except ValueError:
        return None, argv, []

    rest = argv[run_idx + 1 :]
    if not rest or rest[0] in ("-h", "--help"):
        print(
            "Usage: cc-dump [flags...] run <config-name> [flags...] [-- tool-extra-args...]"
            "\n\nStart cc-dump and immediately auto-launch the named config."
            "\nLaunch settings come from the saved launch config."
            "\nArguments after '--' are appended to the config's extra args."
            "\n\nExamples:"
            "\n  cc-dump run claude"
            "\n  cc-dump run claude --port 5000"
            "\n  cc-dump run haiku --port 5000 -- --continue"
        )
        sys.exit(0)
    config_name = rest[0]
    after_name = rest[1:]
    separator_idx = after_name.index("--") if "--" in after_name else len(after_name)
    flags_before = argv[:run_idx]
    flags_after = after_name[:separator_idx]
    cc_dump_flags = flags_before + flags_after
    tool_extra_args = after_name[separator_idx + 1 :] if separator_idx < len(after_name) else []
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
        f"Error: unknown launch config '{config_name}'. Available: {available}",
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


def _short_recording_hash(timestamp: str) -> str:
    payload = f"{timestamp}:{os.getpid()}:{uuid.uuid4().hex}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _recording_path(recordings_dir: Path, timestamp: str) -> str:
    # [LAW:one-source-of-truth] HAR filename is derived from timestamp + short hash.
    filename = f"ccdump-{timestamp}-{_short_recording_hash(timestamp)}.har"
    return str(recordings_dir / filename)


@dataclass(frozen=True)
class ProxyRuntime:
    """Runtime-owned proxy binding for the Anthropic endpoint.

    // [LAW:no-mode-explosion] One provider means one server/handler/endpoint,
    //   not a tuple of bindings keyed by provider.
    // [LAW:one-source-of-truth] The active proxy topology is one value.
    """

    server: http.server.ThreadingHTTPServer
    handler_class: type[ProxyHandler]
    port: int
    endpoint: cc_dump.providers.ProviderEndpoint
    state: "ProviderRuntimeState"


ProviderRuntimeState = cc_dump.core.formatting_impl.ProviderRuntimeState


def _new_provider_state() -> ProviderRuntimeState:
    return ProviderRuntimeState()


def _start_proxy_server(host, port, handler_class):
    """Create and start an HTTP proxy server. Returns (server, actual_port, thread)."""
    srv = http.server.ThreadingHTTPServer((host, port), handler_class)
    ap = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, ap, t


def _build_proxy_runtime(
    *,
    args: argparse.Namespace,
    event_q: queue.Queue[PipelineEvent],
) -> ProxyRuntime:
    provider_target = str(args.target).rstrip("/")
    handler = make_handler_class(
        target_host=provider_target,
        event_queue=event_q,
    )
    server, port, _thread = _start_proxy_server(args.host, int(args.port), handler)
    endpoint = cc_dump.providers.default_provider_endpoint(args.host, port, provider_target)
    return ProxyRuntime(
        server=server,
        handler_class=handler,
        port=port,
        endpoint=endpoint,
        state=_new_provider_state(),
    )


def _base_store_context(
    *,
    tmux_controller,
    settings_store,
    view_store,
) -> dict[str, object]:
    return {
        "tmux_controller": tmux_controller,
        "settings_store": settings_store,
        "view_store": view_store,
    }


def _app_store_context(base_context: dict[str, object], app: CcDumpApp) -> dict[str, object]:
    return {
        **base_context,
        "app": app,
    }


def _shutdown_proxy(proxy_runtime: ProxyRuntime, *, timeout: float) -> None:
    shutdown_thread = threading.Thread(target=proxy_runtime.server.shutdown, daemon=True)
    shutdown_thread.start()
    try:
        shutdown_thread.join(timeout=timeout)
    except KeyboardInterrupt:
        pass
    if shutdown_thread.is_alive():
        logger.warning("Timeout during shutdown - forcing close")
    proxy_runtime.server.server_close()


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


ReplayData = list[ReplayPair]


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
) -> tuple[list[cc_dump.pipeline.har_recorder.HARRecordingSubscriber], str | None]:
    if args.no_record:
        print("   Recording: disabled (--no-record)")
        return [], None

    # [LAW:one-source-of-truth] Recording output directory is centralized in one resolver.
    recordings_dir = _recordings_output_dir(args.record)
    recordings_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")

    record_path = _recording_path(recordings_dir, timestamp)
    recorder = cc_dump.pipeline.har_recorder.HARRecordingSubscriber(record_path)
    router.add_subscriber(DirectSubscriber(recorder.on_event))
    print(f"   Recording: {record_path} (created on first API call)")
    return [recorder], record_path


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
    proxy_runtime: ProxyRuntime,
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
    logger.info("Shutting down gracefully (press Ctrl+C again to force quit)...")
    _shutdown_proxy(proxy_runtime, timeout=3.0)

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
        event_q=event_q,
    )
    actual_port = proxy_runtime.port
    default_target = proxy_runtime.endpoint.target
    state = proxy_runtime.state
    # // [LAW:one-source-of-truth] Single-entry endpoint map feeds the launcher /
    # //   tmux path (slice .5 collapses that path to the bare endpoint).
    provider_endpoints = {default_provider_key: proxy_runtime.endpoint}

    print("🚀 cc-dump proxy started")
    for line in cc_dump.providers.build_provider_endpoint_detail_lines(proxy_runtime.endpoint):
        print(f"   {line}")

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
    )

    # Tmux integration (optional — no-op when not in tmux or libtmux missing)
    # Create settings store (reactive, hot-reloadable)
    settings_store = cc_dump.app.settings_store.create()

    tmux_ctrl, active_launcher_label, tmux_state_cls = _build_tmux_controller(provider_endpoints)
    print(f"   Tmux: {_tmux_status_message(tmux_ctrl, tmux_state_cls, active_launcher_label)}")

    # Request pipeline — interceptors run before forwarding
    pipeline = RequestPipeline(
        interceptors=[cc_dump.pipeline.sentinel.make_interceptor(tmux_ctrl)],
    )
    # // [LAW:single-enforcer] One shared request pipeline is applied at the handler boundary.
    proxy_runtime.handler_class.request_pipeline = pipeline

    router.start()

    # Create view store (reactive, hot-reloadable)
    view_store = cc_dump.app.view_store.create()

    # Create domain store (owns FormattedBlock trees, persists across hot-reload)
    domain_store = cc_dump.app.domain_store.DomainStore()

    # Wire settings store reactions (after all consumers are created)
    store_context = _base_store_context(
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
        analytics_store=analytics_store,
        host=args.host,
        port=actual_port,
        target=default_target,
        replay_data=replay_data,
        recording_path=primary_record_path,
        replay_file=args.replay,
        tmux_controller=tmux_ctrl,
        settings_store=settings_store,
        view_store=view_store,
        domain_store=domain_store,
        store_context=store_context,
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
            proxy_runtime=proxy_runtime,
            router=router,
            har_recorders=har_recorders,
            actual_port=actual_port,
            primary_record_path=primary_record_path,
            replay_arg=args.replay,
        )
