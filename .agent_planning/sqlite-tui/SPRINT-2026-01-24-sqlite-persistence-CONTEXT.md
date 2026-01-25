# Implementation Context: sqlite-persistence
Generated: 2026-01-24

## Files to Create
- `src/cc_dump/schema.py`
- `src/cc_dump/store.py`

## Files to Modify
- `src/cc_dump/cli.py` — add --db/--no-db flags, wire SQLiteWriter

## Key Implementation Details

### schema.py

```python
import sqlite3
import os

SCHEMA_VERSION = 1

def init_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _create_tables(conn)
    return conn

def _create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS blobs (
            hash TEXT PRIMARY KEY,
            content BLOB NOT NULL,
            byte_size INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            sequence_num INTEGER NOT NULL,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            model TEXT,
            stop_reason TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_creation_tokens INTEGER DEFAULT 0,
            tool_names TEXT,
            request_json TEXT,
            response_json TEXT,
            text_content TEXT
        );

        CREATE TABLE IF NOT EXISTS turn_blobs (
            turn_id INTEGER NOT NULL REFERENCES turns(id),
            blob_hash TEXT NOT NULL REFERENCES blobs(hash),
            field_path TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
            text_content,
            content=turns,
            content_rowid=id
        );

        CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
        CREATE INDEX IF NOT EXISTS idx_turn_blobs_turn ON turn_blobs(turn_id);
    """)
    conn.commit()
```

### store.py - SQLiteWriter

```python
import hashlib
import json
import sys
import sqlite3
from cc_dump.schema import init_db

BLOB_THRESHOLD = 512  # bytes

class SQLiteWriter:
    def __init__(self, db_path: str, session_id: str):
        self._conn = init_db(db_path)
        self._session_id = session_id
        self._seq = 0
        self._current_request = None
        self._current_response_events = []
        self._current_text = []
        self._current_usage = {}
        self._current_stop = ""
        self._current_model = ""

    def on_event(self, event):
        try:
            self._handle(event)
        except Exception as e:
            sys.stderr.write(f"[db] error: {e}\n")
            sys.stderr.flush()

    def _handle(self, event):
        kind = event[0]
        if kind == "request":
            self._current_request = event[1]
            self._current_response_events = []
            self._current_text = []
            self._current_usage = {}
            self._current_stop = ""
            self._current_model = self._current_request.get("model", "")

        elif kind == "response_event":
            event_type, data = event[1], event[2]
            self._current_response_events.append(data)
            if event_type == "message_start":
                msg = data.get("message", {})
                usage = msg.get("usage", {})
                self._current_usage = usage
                self._current_model = msg.get("model", self._current_model)
            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    self._current_text.append(delta.get("text", ""))
            elif event_type == "message_delta":
                delta = data.get("delta", {})
                self._current_stop = delta.get("stop_reason", "")
                # Accumulate final usage
                usage = data.get("usage", {})
                if usage:
                    self._current_usage.update(usage)

        elif kind == "response_done":
            self._commit_turn()

    def _commit_turn(self):
        if not self._current_request:
            return
        self._seq += 1

        # Blobify request and response
        req_json, req_blobs = self._blobify(self._current_request)
        resp_json, resp_blobs = self._blobify(self._current_response_events)

        # Extract tool names
        tools = self._current_request.get("tools", [])
        tool_names = json.dumps([t.get("name", "") for t in tools]) if tools else None

        text_content = "".join(self._current_text)

        # Insert turn
        cur = self._conn.execute("""
            INSERT INTO turns (session_id, sequence_num, model, stop_reason,
                input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                tool_names, request_json, response_json, text_content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self._session_id, self._seq, self._current_model, self._current_stop,
            self._current_usage.get("input_tokens", 0),
            self._current_usage.get("output_tokens", 0),
            self._current_usage.get("cache_read_input_tokens", 0),
            self._current_usage.get("cache_creation_input_tokens", 0),
            tool_names, json.dumps(req_json), json.dumps(resp_json), text_content,
        ))
        turn_id = cur.lastrowid

        # Insert blobs and turn_blobs
        all_blobs = req_blobs + resp_blobs
        for blob_hash, content, field_path in all_blobs:
            self._conn.execute(
                "INSERT OR IGNORE INTO blobs (hash, content, byte_size) VALUES (?, ?, ?)",
                (blob_hash, content.encode(), len(content.encode()))
            )
            self._conn.execute(
                "INSERT INTO turn_blobs (turn_id, blob_hash, field_path) VALUES (?, ?, ?)",
                (turn_id, blob_hash, field_path)
            )

        # FTS
        if text_content:
            self._conn.execute(
                "INSERT INTO turns_fts (rowid, text_content) VALUES (?, ?)",
                (turn_id, text_content)
            )

        self._conn.commit()
        self._current_request = None

    def _blobify(self, obj, path=""):
        """Replace large strings with blob references, return (modified_obj, blobs_list)."""
        blobs = []
        result = self._blobify_walk(obj, path, blobs)
        return result, blobs

    def _blobify_walk(self, obj, path, blobs):
        if isinstance(obj, str):
            if len(obj.encode()) >= BLOB_THRESHOLD:
                h = hashlib.sha256(obj.encode()).hexdigest()
                blobs.append((h, obj, path))
                return {"__blob__": h}
            return obj
        elif isinstance(obj, dict):
            return {k: self._blobify_walk(v, f"{path}.{k}", blobs) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._blobify_walk(v, f"{path}[{i}]", blobs) for i, v in enumerate(obj)]
        return obj
```

### cli.py additions

```python
import uuid
from cc_dump.router import EventRouter, QueueSubscriber, DirectSubscriber
from cc_dump.store import SQLiteWriter

parser.add_argument("--db", type=str, default=os.path.expanduser("~/.local/share/cc-dump/sessions.db"))
parser.add_argument("--no-db", action="store_true")

# After router creation:
if not args.no_db:
    session_id = uuid.uuid4().hex
    writer = SQLiteWriter(args.db, session_id)
    router.add_subscriber(DirectSubscriber(writer.on_event))
```
