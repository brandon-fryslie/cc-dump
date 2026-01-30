"""CLI entry point for cc-dump."""

import argparse
import http.server
import os
import queue
import threading
import uuid

from cc_dump.proxy import ProxyHandler
from cc_dump.router import EventRouter, QueueSubscriber, DirectSubscriber
from cc_dump.store import SQLiteWriter


def main():
    parser = argparse.ArgumentParser(description="Claude Code API monitor proxy")
    target = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=3344)
    parser.add_argument("--target", type=str, default=target,
                        help="Upstream API URL for reverse proxy mode (default: https://api.anthropic.com)")
    parser.add_argument("--db", type=str, default=os.path.expanduser("~/.local/share/cc-dump/sessions.db"), help="SQLite database path")
    parser.add_argument("--no-db", action="store_true", help="Disable persistence (no database)")
    args = parser.parse_args()

    ProxyHandler.target_host = args.target.rstrip("/") if args.target else None

    event_q = queue.Queue()
    ProxyHandler.event_queue = event_q

    server = http.server.HTTPServer((args.host, args.port), ProxyHandler)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(f"🚀 cc-dump proxy started")
    print(f"   Listening on: http://{args.host}:{args.port}")
    if ProxyHandler.target_host:
        print(f"   Reverse proxy mode: {ProxyHandler.target_host}")
        print(f"   Usage: ANTHROPIC_BASE_URL=http://{args.host}:{args.port} claude")
    else:
        print(f"   Forward proxy mode (dynamic targets)")
        print(f"   Usage: HTTP_PROXY=http://{args.host}:{args.port} ANTHROPIC_BASE_URL=http://api.minimax.com claude")

    # State dict for content tracking (used by formatting layer)
    state = {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
    }

    # Set up event router with subscribers
    router = EventRouter(event_q)

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
        print(f"   Database: disabled (--no-db)")

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
        db_path=db_path,
        session_id=session_id,
        host=args.host,
        port=args.port,
        target=ProxyHandler.target_host
    )
    try:
        app.run()
    finally:
        router.stop()
        server.shutdown()
