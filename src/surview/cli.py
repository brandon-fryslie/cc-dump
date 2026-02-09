"""CLI entry point for surview."""

import argparse
import http.server
import os
import queue
import threading
import uuid

from surview.proxy import ProxyHandler
from surview.router import EventRouter, QueueSubscriber, DirectSubscriber
from surview.store import SQLiteWriter


def main():
    parser = argparse.ArgumentParser(description="Claude Code API monitor proxy")
    target = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=0, help="Port to bind (default: 0, OS-assigned)")
    parser.add_argument("--target", type=str, default=target,
                        help="Upstream API URL for reverse proxy mode (default: https://api.anthropic.com)")
    parser.add_argument("--db", type=str, default=os.path.expanduser("~/.local/share/surview/sessions.db"), help="SQLite database path")
    parser.add_argument("--no-db", action="store_true", help="Disable persistence (no database)")
    parser.add_argument("--record", type=str, default=None, help="HAR recording output path")
    parser.add_argument("--no-record", action="store_true", help="Disable HAR recording")
    parser.add_argument("--replay", type=str, default=None,
                        help="Replay a recorded session (path to .har file)")
    parser.add_argument("--seed-hue", type=float, default=None,
                        help="Seed hue (0-360) for color palette (default: 190, cyan). Env: CC_DUMP_SEED_HUE")
    args = parser.parse_args()

    # Initialize color palette before anything else imports it
    import surview.palette
    surview.palette.init_palette(args.seed_hue)

    event_q = queue.Queue()

    # Set up CA for MITM (before creating server)
    ca_cert = None
    ca_key = None
    ca_pem_path = None
    if not args.replay:
        import surview.certs
        ca_cert, ca_key, ca_pem_path = surview.certs.ensure_ca()

        # Check if CA is trusted and print instructions if not
        if not surview.certs.check_ca_trusted(ca_pem_path):
            print("⚠️  CA certificate not trusted by system")
            surview.certs.print_trust_instructions(ca_pem_path)
            print()

    # Replay mode or live mode
    server = None
    replay_data = None
    actual_port = args.port
    if args.replay:
        # Replay mode: load HAR (complete messages, NO event conversion)
        import surview.har_replayer

        print("🎬 surview replay mode")
        print(f"   Loading: {args.replay}")

        try:
            replay_data = surview.har_replayer.load_har(args.replay)
            print(f"   Found {len(replay_data)} request/response pairs")

        except Exception as e:
            print(f"   Error loading HAR file: {e}")
            return
    else:
        # Live mode: start proxy server
        ProxyHandler.target_host = args.target.rstrip("/") if args.target else None
        ProxyHandler.event_queue = event_q
        ProxyHandler.ca_cert = ca_cert
        ProxyHandler.ca_key = ca_key

        server = http.server.HTTPServer((args.host, args.port), ProxyHandler)
        actual_port = server.server_address[1]  # Get OS-assigned port

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        print("🚀 surview proxy started")
        print(f"   Listening on: http://{args.host}:{actual_port}")
        if ca_pem_path:
            print(f"   CA certificate: {ca_pem_path}")
        print()
        if ProxyHandler.target_host:
            print(f"   Reverse proxy mode: {ProxyHandler.target_host}")
            print(f"   Usage: ANTHROPIC_BASE_URL=http://{args.host}:{actual_port} claude")
        else:
            print("   Forward/MITM proxy mode")
            print(f"   HTTP_PROXY=http://{args.host}:{actual_port}")
            print(f"   HTTPS_PROXY=http://{args.host}:{actual_port}")
        print()

    # State dict for content tracking (used by formatting layer)
    state = {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
    }

    # Set up event router with subscribers
    # Live mode: apply event adapter transform
    # Replay mode: no transform (replayer already emits handler-format events)
    if args.replay:
        router = EventRouter(event_q)
    else:
        import surview.event_adapter
        router = EventRouter(event_q, transform=surview.event_adapter.adapt_proxy_event)

    # Display subscriber (queue-based for async consumption)
    display_sub = QueueSubscriber()
    router.add_subscriber(display_sub)

    # SQLite writer (direct subscriber, inline writes)
    session_id = None
    db_path = None
    if not args.no_db:
        session_id = uuid.uuid4().hex
        db_path = args.db
        writer = SQLiteWriter(db_path, session_id)
        router.add_subscriber(DirectSubscriber(writer.on_event))
        print(f"   Database: {db_path}")
        print(f"   Session ID: {session_id}")
    else:
        print("   Database: disabled (--no-db)")

    # HAR recording subscriber (direct subscriber, inline writes)
    har_recorder = None
    if not args.no_record:
        # Generate session_id if not already created for database
        if session_id is None:
            session_id = uuid.uuid4().hex

        import surview.har_recorder
        record_dir = os.path.expanduser("~/.local/share/surview/recordings")
        os.makedirs(record_dir, exist_ok=True)
        record_path = args.record or os.path.join(record_dir, f"recording-{session_id}.har")
        har_recorder = surview.har_recorder.HARRecordingSubscriber(record_path, session_id)
        router.add_subscriber(DirectSubscriber(har_recorder.on_event))
        print(f"   Recording: {record_path}")
    else:
        print("   Recording: disabled (--no-record)")

    router.start()

    # Initialize hot-reload watcher
    import surview.hot_reload
    package_dir = os.path.dirname(os.path.abspath(__file__))
    surview.hot_reload.init(package_dir)

    # Launch TUI with database context
    from surview.tui.app import SurviewApp

    app = SurviewApp(
        display_sub.queue,
        state,
        router,
        db_path=db_path,
        session_id=session_id,
        host=args.host if not args.replay else None,
        port=actual_port if not args.replay else None,
        target=ProxyHandler.target_host if not args.replay else None,
        replay_data=replay_data
    )
    try:
        app.run()
    finally:
        router.stop()
        if har_recorder:
            har_recorder.close()
        if server:
            server.shutdown()
