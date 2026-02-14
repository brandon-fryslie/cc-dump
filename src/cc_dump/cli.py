"""CLI entry point for cc-dump."""

import argparse
import http.server
import os
import queue
import sys
import threading
import uuid

from cc_dump.proxy import ProxyHandler
from cc_dump.router import EventRouter, QueueSubscriber, DirectSubscriber
from cc_dump.analytics_store import AnalyticsStore


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
        "--seed-hue",
        type=float,
        default=None,
        help="Seed hue (0-360) for color palette (default: 190, cyan). Env: CC_DUMP_SEED_HUE",
    )
    args = parser.parse_args()

    # Initialize color palette before anything else imports it
    import cc_dump.palette

    cc_dump.palette.init_palette(args.seed_hue)

    # Resolve --continue to load latest recording
    if args.continue_session:
        import cc_dump.sessions

        latest = cc_dump.sessions.get_latest_recording()
        if latest is None:
            print("No recordings found to continue from.")
            return
        args.replay = latest
        print(f"🔄 Continuing from: {latest}")

    from cc_dump.event_types import PipelineEvent

    event_q: queue.Queue[PipelineEvent] = queue.Queue()

    # Load replay data if specified, but always start proxy
    server = None
    replay_data = None

    if args.replay:
        # Load HAR file (complete messages, NO event conversion)
        import cc_dump.har_replayer

        print(f"   Loading replay: {args.replay}")

        try:
            replay_data = cc_dump.har_replayer.load_har(args.replay)
            print(f"   Found {len(replay_data)} request/response pairs")

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
            f"   Usage: HTTP_PROXY=http://{args.host}:{actual_port} ANTHROPIC_BASE_URL=http://api.minimax.com claude"
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
    session_id = uuid.uuid4().hex
    analytics_store = AnalyticsStore()
    router.add_subscriber(DirectSubscriber(analytics_store.on_event))
    print(f"   Session ID: {session_id}")

    # HAR recording subscriber (direct subscriber, inline writes)
    # [LAW:one-source-of-truth] Session name from CLI or default
    session_name = args.session
    har_recorder = None
    record_path = None
    if not args.no_record:
        import cc_dump.har_recorder

        # [LAW:one-source-of-truth] Recordings organized by session name
        record_dir = os.path.expanduser("~/.local/share/cc-dump/recordings")
        session_dir = os.path.join(record_dir, session_name)
        os.makedirs(session_dir, exist_ok=True)
        record_path = args.record or os.path.join(
            session_dir, f"recording-{session_id}.har"
        )
        har_recorder = cc_dump.har_recorder.HARRecordingSubscriber(
            record_path, session_id
        )
        router.add_subscriber(DirectSubscriber(har_recorder.on_event))
        print(f"   Recording: {record_path} (created on first API call)")
    else:
        print("   Recording: disabled (--no-record)")

    # Tmux integration (optional — no-op when not in tmux or libtmux missing)
    import cc_dump.tmux_controller

    tmux_ctrl = None
    if cc_dump.tmux_controller.is_available():
        tmux_ctrl = cc_dump.tmux_controller.TmuxController()
        tmux_ctrl.set_port(actual_port)
        if tmux_ctrl.state == cc_dump.tmux_controller.TmuxState.READY:
            router.add_subscriber(DirectSubscriber(tmux_ctrl.on_event))
            print("   Tmux: available (press 'c' to launch claude)")

    router.start()

    # Initialize hot-reload watcher
    import cc_dump.hot_reload

    package_dir = os.path.dirname(os.path.abspath(__file__))
    cc_dump.hot_reload.init(package_dir)

    # Launch TUI with database context
    from cc_dump.tui.app import CcDumpApp

    app = CcDumpApp(
        display_sub.queue,
        state,
        router,
        analytics_store=analytics_store,
        session_id=session_id,
        session_name=session_name,
        host=args.host,
        port=actual_port,
        target=ProxyHandler.target_host,
        replay_data=replay_data,
        recording_path=record_path,
        replay_file=args.replay,
        tmux_controller=tmux_ctrl,
    )
    try:
        app.run()
    finally:
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
