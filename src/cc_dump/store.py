"""SQLite-backed event store for API conversation persistence.

Accumulates request/response pairs into complete "turns", extracts large strings
to blob storage, and maintains FTS index for search.
"""

import hashlib
import json
import sys

from cc_dump.analysis import correlate_tools
from cc_dump.schema import init_db
from cc_dump.token_counter import count_tokens

BLOB_THRESHOLD = 512  # bytes - strings >= this size get extracted to blobs table


class SQLiteWriter:
    """Event subscriber that persists API conversations to SQLite."""

    def __init__(self, db_path: str, session_id: str):
        self._conn = init_db(db_path)
        self._session_id = session_id
        self._seq = 0

        # Accumulate state for current turn
        self._current_request = None
        self._current_response_events = []
        self._current_text = []
        self._current_usage = {}
        self._current_stop = ""
        self._current_model = ""

    def on_event(self, event):
        """Handle an event from the router. Errors logged, never crash the proxy."""
        try:
            self._handle(event)
        except Exception as e:
            import traceback

            sys.stderr.write("[db] error: {}\n".format(e))
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()

    def _handle(self, event):
        """Internal event handler - may raise exceptions."""
        kind = event[0]

        if kind == "request":
            # Start accumulating a new turn
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
                self._current_usage = dict(usage)
                self._current_model = msg.get("model", self._current_model)

            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    self._current_text.append(delta.get("text", ""))

            elif event_type == "message_delta":
                delta = data.get("delta", {})
                self._current_stop = delta.get("stop_reason", "")
                # Accumulate final usage (output tokens)
                usage = data.get("usage", {})
                if usage:
                    self._current_usage.update(usage)

        elif kind == "response_done":
            self._commit_turn()

    def _commit_turn(self):
        """Write accumulated turn to database."""
        if not self._current_request:
            return

        self._seq += 1

        # Blobify request and response (extract large strings)
        req_json, req_blobs = self._blobify(self._current_request)
        resp_json, resp_blobs = self._blobify(self._current_response_events)

        # Extract tool names for quick filtering
        tools = self._current_request.get("tools", [])
        tool_names = json.dumps([t.get("name", "") for t in tools]) if tools else None

        # Concatenate all text deltas
        text_content = "".join(self._current_text)

        # Insert turn row
        cur = self._conn.execute(
            """
            INSERT INTO turns (
                session_id, sequence_num, model, stop_reason,
                input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                tool_names, request_json, response_json, text_content
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                self._session_id,
                self._seq,
                self._current_model,
                self._current_stop,
                self._current_usage.get("input_tokens", 0),
                self._current_usage.get("output_tokens", 0),
                self._current_usage.get("cache_read_input_tokens", 0),
                self._current_usage.get("cache_creation_input_tokens", 0),
                tool_names,
                json.dumps(req_json),
                json.dumps(resp_json),
                text_content,
            ),
        )

        turn_id = cur.lastrowid

        # Insert blobs and turn_blobs links
        all_blobs = req_blobs + resp_blobs
        for blob_hash, content, field_path in all_blobs:
            # INSERT OR IGNORE ensures deduplication (same hash = same content)
            self._conn.execute(
                "INSERT OR IGNORE INTO blobs (hash, content, byte_size) VALUES (?, ?, ?)",
                (blob_hash, content.encode("utf-8"), len(content.encode("utf-8"))),
            )
            self._conn.execute(
                "INSERT INTO turn_blobs (turn_id, blob_hash, field_path) VALUES (?, ?, ?)",
                (turn_id, blob_hash, field_path),
            )

        # Persist tool invocations with token counts
        messages = self._current_request.get("messages", [])
        invocations = correlate_tools(messages)
        for inv in invocations:
            # Count actual tokens using tiktoken
            input_tokens = count_tokens(inv.input_str)
            result_tokens = count_tokens(inv.result_str)

            self._conn.execute(
                """
                INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    turn_id,
                    inv.name,
                    inv.tool_use_id,
                    inv.input_bytes,
                    inv.result_bytes,
                    input_tokens,
                    result_tokens,
                    int(inv.is_error),
                ),
            )

        # Insert into FTS table for search
        if text_content:
            self._conn.execute(
                "INSERT INTO turns_fts (rowid, text_content) VALUES (?, ?)",
                (turn_id, text_content),
            )

        self._conn.commit()

        # Clear accumulator
        self._current_request = None

    def _blobify(self, obj, path=""):
        """Replace large strings with blob references, return (modified_obj, blobs_list).

        blobs_list contains tuples of (hash, content, field_path).
        """
        blobs = []
        result = self._blobify_walk(obj, path, blobs)
        return result, blobs

    def _blobify_walk(self, obj, path, blobs):
        """Recursively walk object structure, extracting large strings to blobs."""
        if isinstance(obj, str):
            if len(obj.encode("utf-8")) >= BLOB_THRESHOLD:
                h = hashlib.sha256(obj.encode("utf-8")).hexdigest()
                blobs.append((h, obj, path))
                return {"__blob__": h}
            return obj

        elif isinstance(obj, dict):
            return {
                k: self._blobify_walk(v, "{}.{}".format(path, k), blobs)
                for k, v in obj.items()
            }

        elif isinstance(obj, list):
            return [
                self._blobify_walk(v, "{}[{}]".format(path, i), blobs)
                for i, v in enumerate(obj)
            ]

        return obj
