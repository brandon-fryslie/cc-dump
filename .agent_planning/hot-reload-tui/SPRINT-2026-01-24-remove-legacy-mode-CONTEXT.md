# Implementation Context: remove-legacy-mode

## Files to Modify

### cli.py — Heavy edits
Current structure:
- Lines 1-11: imports (remove cc_dump.colors, cc_dump.display, cc_dump.formatting, cc_dump.formatting_ansi, importlib, os)
- Lines 22-25: ANSI constants (delete — only used for legacy prints)
- Lines 27-52: `_pkg_dir`, `_mtimes`, `_check_reload()` (delete — reimplemented in sprint 2)
- Line 59: `--no-tui` argument (delete)
- Lines 74-82: Legacy startup prints inside `if args.no_tui:` (delete)
- Lines 83-91: Legacy `state` dict (delete — TUI has its own)
- Lines 106-119: Legacy consumer loop `if args.no_tui:` branch (delete)
- Lines 120-129: TUI launch in `else:` branch (keep, but remove the `else` — it becomes the only path)

After edits, cli.py should be roughly:
```python
"""CLI entry point for cc-dump."""

import argparse
import http.server
import queue
import threading
import uuid

from cc_dump.proxy import ProxyHandler
from cc_dump.router import EventRouter, QueueSubscriber, DirectSubscriber
from cc_dump.store import SQLiteWriter


def main():
    parser = argparse.ArgumentParser(description="Claude Code API monitor proxy")
    parser.add_argument("--port", type=int, default=3344)
    parser.add_argument("--target", type=str, default="https://api.anthropic.com")
    parser.add_argument("--db", type=str, default=os.path.expanduser("~/.local/share/cc-dump/sessions.db"))
    parser.add_argument("--no-db", action="store_true", help="Disable persistence")
    args = parser.parse_args()

    ProxyHandler.target_host = args.target.rstrip("/")

    event_q = queue.Queue()
    ProxyHandler.event_queue = event_q

    server = http.server.HTTPServer(("127.0.0.1", args.port), ProxyHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    router = EventRouter(event_q)

    display_sub = QueueSubscriber()
    router.add_subscriber(display_sub)

    if not args.no_db:
        session_id = uuid.uuid4().hex
        writer = SQLiteWriter(args.db, session_id)
        router.add_subscriber(DirectSubscriber(writer.on_event))

    router.start()

    from cc_dump.tui.app import CcDumpApp
    app = CcDumpApp(display_sub.queue, state={}, router)  # TUI manages its own state
    try:
        app.run()
    finally:
        router.stop()
        server.shutdown()
```

Note: Need to check if CcDumpApp uses the `state` param passed in. If so, keep passing an empty dict or refactor.

### formatting.py — Minor edit
- Line 4: Remove comment referencing `formatting_ansi.py`

### Files to Delete
- `src/cc_dump/display.py`
- `src/cc_dump/formatting_ansi.py`

## Key Concern: TUI's state parameter
The TUI app constructor takes `state` as a parameter. Check `tui/app.py` to see if it uses the legacy state dict or manages its own. If it uses the passed-in state, we keep passing it (it's just a plain dict). The key point is that cli.py no longer owns the consumer loop — the TUI does.
