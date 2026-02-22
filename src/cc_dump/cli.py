"""CLI entry point for cc-dump."""

import argparse
import http.server
import os
import queue
import signal
import sys
import threading
from datetime import datetime

from cc_dump.proxy import ProxyHandler
from cc_dump.router import EventRouter, QueueSubscriber, DirectSubscriber
from cc_dump.analytics_store import AnalyticsStore
import cc_dump.stderr_tee
import cc_dump.palette
import cc_dump.sessions
from cc_dump.event_types import PipelineEvent
import cc_dump.har_replayer
import cc_dump.har_recorder
import cc_dump.settings
import cc_dump.tmux_controller
import cc_dump.settings_store
import cc_dump.launch_config
import cc_dump.side_channel
import cc_dump.data_dispatcher
import cc_dump.sentinel
import cc_dump.session_sidecar
from cc_dump.proxy import RequestPipeline
import cc_dump.view_store
import cc_dump.hot_reload
import cc_dump.domain_store
import cc_dump.tui.view_store_bridge
from cc_dump.tui.app import CcDumpApp


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
    args = parser.parse_args()

    # Install stderr tee before anything else writes to stderr
    cc_dump.stderr_tee.install()

    # Initialize color palette before anything else imports it
    cc_dump.palette.init_palette(args.seed_hue)

    if args.list_recordings:
        recordings = cc_dump.sessions.list_recordings()
        cc_dump.sessions.print_recordings_list(recordings)
        return

    if args.cleanup_recordings is not None:
        result = cc_dump.sessions.cleanup_recordings(
            keep=args.cleanup_recordings,
            dry_run=bool(args.cleanup_dry_run),
        )
        mode = "Dry run" if result["dry_run"] else "Cleanup"
        print(
            f"{mode}: removed {result['removed']} recording(s), "
            f"kept {result['kept']}, freed {cc_dump.sessions.format_size(result['bytes_freed'])}"
        )
        if result["removed_paths"]:
            for path in result["removed_paths"]:
                print(f"  - {path}")
        return

    # Resolve --continue / --resume to load latest recording
    if args.resume is not None:
        if args.resume == "latest":
            latest = cc_dump.sessions.get_latest_recording()
            if latest is None:
                print("No recordings found to resume from.")
                return
            args.replay = latest
        else:
            args.replay = args.resume
        print(f"🔄 Resuming from: {args.replay}")

    if args.continue_session:
        latest = cc_dump.sessions.get_latest_recording()
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
            replay_data = cc_dump.har_replayer.load_har(args.replay)
            print(f"   Found {len(replay_data)} request/response pairs")
            sidecar_payload = cc_dump.session_sidecar.load_ui_state(args.replay)
            if isinstance(sidecar_payload, dict):
                loaded_ui = sidecar_payload.get("ui_state", {})
                if isinstance(loaded_ui, dict):
                    resume_ui_state = loaded_ui
                    print(f"   Loaded UI sidecar: {cc_dump.session_sidecar.sidecar_path_for_har(args.replay)}")

        except Exception as e:
            print(f"   Error loading HAR file: {e}")
            return

    # Always start proxy server
    ProxyHandler.target_host = args.target.rstrip("/") if args.target else None
    ProxyHandler.event_queue = event_q

    server = http.server.ThreadingHTTPServer((args.host, args.port), ProxyHandler)

    # Get the actual port assigned by the OS (important when args.port=0)
    actual_port = server.server_address[1]

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print("🚀 cc-dump proxy started")
    print(f"   Listening on: http://{args.host}:{actual_port}")
    if ProxyHandler.target_host:
        print(f"   Reverse proxy mode: {ProxyHandler.target_host}")
        print(f"   Usage: ANTHROPIC_BASE_URL=http://{args.host}:{actual_port} claude")
    else:
        print("   Forward proxy mode (dynamic targets)")
        print(
            f"   Usage: HTTP_PROXY=http://{args.host}:{actual_port} ANTHROPIC_BASE_URL=https://api.anthropic.com claude"
        )

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
    har_recorder = None
    record_path = None
    if not args.no_record:
        # [LAW:one-source-of-truth] Recordings organized by session name
        record_dir = os.path.expanduser("~/.local/share/cc-dump/recordings")
        session_dir = os.path.join(record_dir, session_name)
        os.makedirs(session_dir, exist_ok=True)
        record_path = args.record or os.path.join(
            session_dir, f"recording-{datetime.now().strftime('%Y%m%d-%H%M%S')}.har"
        )
        har_recorder = cc_dump.har_recorder.HARRecordingSubscriber(record_path)
        router.add_subscriber(DirectSubscriber(har_recorder.on_event))
        print(f"   Recording: {record_path} (created on first API call)")
    else:
        print("   Recording: disabled (--no-record)")

    # Tmux integration (optional — no-op when not in tmux or libtmux missing)
    # Create settings store (reactive, hot-reloadable)
    settings_store = cc_dump.settings_store.create()

    tmux_ctrl = None
    TmuxState = cc_dump.tmux_controller.TmuxState
    if cc_dump.tmux_controller.is_available():
        active_config = cc_dump.launch_config.get_active_config()
        auto_zoom = bool(settings_store.get("auto_zoom_default"))
        tmux_ctrl = cc_dump.tmux_controller.TmuxController(claude_command=active_config.claude_command, auto_zoom=auto_zoom)
        tmux_ctrl.set_port(actual_port)
        # Subscribe for both READY and CLAUDE_RUNNING (adoption case)
        if tmux_ctrl.state in (TmuxState.READY, TmuxState.CLAUDE_RUNNING):
            router.add_subscriber(DirectSubscriber(tmux_ctrl.on_event))
    # [LAW:dataflow-not-control-flow] Status message from state, not branching
    _TMUX_STATUS = {
        None: "disabled (not in tmux)" if not os.environ.get("TMUX") else "disabled (libtmux not installed)",
        TmuxState.READY: "enabled (press 'c' to launch claude)",
        TmuxState.CLAUDE_RUNNING: "enabled (claude running)",
        TmuxState.NOT_IN_TMUX: "disabled (not in tmux)",
        TmuxState.NO_LIBTMUX: "disabled (libtmux not installed)",
    }
    tmux_state = tmux_ctrl.state if tmux_ctrl else None
    print(f"   Tmux: {_TMUX_STATUS[tmux_state]}")

    # Side channel (AI enrichment via claude -p)
    sc_enabled = bool(settings_store.get("side_channel_enabled"))
    side_channel_mgr = cc_dump.side_channel.SideChannelManager()
    side_channel_mgr.enabled = sc_enabled
    data_dispatcher = cc_dump.data_dispatcher.DataDispatcher(side_channel_mgr)

    # Request pipeline — transforms + interceptors run before forwarding
    pipeline = RequestPipeline(
        transforms=[],
        interceptors=[cc_dump.sentinel.make_interceptor(tmux_ctrl)],
    )
    ProxyHandler.request_pipeline = pipeline

    router.start()

    # Create view store (reactive, hot-reloadable)
    view_store = cc_dump.view_store.create()

    # Create domain store (owns FormattedBlock trees, persists across hot-reload)
    domain_store = cc_dump.domain_store.DomainStore()

    # Wire settings store reactions (after all consumers are created)
    store_context = {
        "side_channel_manager": side_channel_mgr,
        "tmux_controller": tmux_ctrl,
        "settings_store": settings_store,
    }
    settings_store._reaction_disposers = cc_dump.settings_store.setup_reactions(
        settings_store, store_context
    )

    # Initialize hot-reload watcher
    package_dir = os.path.dirname(os.path.abspath(__file__))
    cc_dump.hot_reload.init(package_dir)

    # Launch TUI with database context
    app = CcDumpApp(
        display_sub.queue,
        state,
        router,
        analytics_store=analytics_store,
        session_name=session_name,
        host=args.host,
        port=actual_port,
        target=ProxyHandler.target_host,
        replay_data=replay_data,
        recording_path=record_path,
        replay_file=args.replay,
        resume_ui_state=resume_ui_state,
        tmux_controller=tmux_ctrl,
        side_channel_manager=side_channel_mgr,
        data_dispatcher=data_dispatcher,
        settings_store=settings_store,
        view_store=view_store,
        domain_store=domain_store,
        store_context=store_context,
    )

    # Store context is finalized here; view-store reactions are bound on app mount.
    store_context["app"] = app
    store_context.update(cc_dump.tui.view_store_bridge.build_reaction_context(app))
    try:
        app.run()
    finally:
        # Dump buffered errors to stderr (TUI is gone, terminal is restored)
        if app._error_log:
            print("\n[cc-dump] Errors during session:", file=sys.stderr)
            for line in app._error_log:
                print(f"  {line}", file=sys.stderr)
            sys.stderr.flush()

        # Clean up tmux state (unzoom)
        if tmux_ctrl:
            tmux_ctrl.cleanup()
        # Graceful shutdown with timeout for in-flight requests
        if server:
            print("\n🛑 Shutting down gracefully (press Ctrl+C again to force quit)...", file=sys.stderr)
            sys.stderr.flush()

            # Try graceful shutdown with 3 second timeout
            shutdown_thread = threading.Thread(target=server.shutdown, daemon=True)
            shutdown_thread.start()
            shutdown_thread.join(timeout=3.0)

            if shutdown_thread.is_alive():
                # Timeout - force close
                print("   ⏱️  Timeout - forcing shutdown", file=sys.stderr)
            else:
                # Graceful shutdown succeeded
                print("   ✓ Server stopped", file=sys.stderr)

            server.server_close()

        # Clean up other resources
        router.stop()
        if har_recorder:
            har_recorder.close()

        # Persist UI sidecar next to active HAR (recording path or replay file).
        sidecar_target = (
            record_path if record_path and os.path.exists(record_path)
            else args.replay if args.replay and os.path.exists(args.replay)
            else None
        )
        if sidecar_target:
            try:
                ui_state = app.export_ui_state()
                sidecar_path = cc_dump.session_sidecar.save_ui_state(sidecar_target, ui_state)
                print(f"   UI state saved: {sidecar_path}", file=sys.stderr)
            except Exception as e:
                print(f"   UI state save failed: {e}", file=sys.stderr)

        # Print restart command — unstoppable (mask SIGINT so Ctrl+C can't suppress it)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        replay_path = (
            record_path if record_path and os.path.exists(record_path)
            else args.replay if args.replay and os.path.exists(args.replay)
            else None
        )
        cmd = f"{sys.argv[0]} --port {actual_port}"
        if replay_path:
            cmd += f" --resume {replay_path}"
        print(f"\n   To resume:\n   {cmd}", file=sys.stderr)
        sys.stderr.flush()
        signal.signal(signal.SIGINT, signal.SIG_DFL)
