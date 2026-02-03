"""SQLite schema initialization for session storage.

Tables:
  - blobs: content-addressed binary storage (sha256 hash PK)
  - turns: complete request/response turns with metadata
  - turn_blobs: links turns to extracted blobs
  - turns_fts: full-text search on message content
"""

import os
import sqlite3

SCHEMA_VERSION = 3


def init_db(path: str) -> sqlite3.Connection:
    """Initialize database at the given path, creating tables if needed.

    Returns a connection configured for WAL mode and safe concurrent access.
    """
    # Ensure parent directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)

    # Enable WAL mode for better concurrency and crash recovery
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    _create_tables(conn)
    _migrate_v2_to_v3(conn)

    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create all schema tables if they don't exist."""
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

        CREATE TABLE IF NOT EXISTS tool_invocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id INTEGER NOT NULL REFERENCES turns(id),
            tool_name TEXT NOT NULL,
            tool_use_id TEXT NOT NULL,
            input_bytes INTEGER NOT NULL DEFAULT 0,
            result_bytes INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            result_tokens INTEGER NOT NULL DEFAULT 0,
            is_error INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
        CREATE INDEX IF NOT EXISTS idx_turn_blobs_turn ON turn_blobs(turn_id);
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_turn ON tool_invocations(turn_id);

        -- Performance optimization indexes
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_composite ON tool_invocations(turn_id, tool_name);
        CREATE INDEX IF NOT EXISTS idx_turns_session_seq ON turns(session_id, sequence_num);
    """)

    conn.commit()


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add token count columns to tool_invocations (migration from schema v2 to v3).

    Idempotent: checks if columns exist before adding them.
    """
    cursor = conn.execute("PRAGMA table_info(tool_invocations)")
    columns = {row[1] for row in cursor.fetchall()}

    if "input_tokens" not in columns:
        conn.execute("ALTER TABLE tool_invocations ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0")

    if "result_tokens" not in columns:
        conn.execute("ALTER TABLE tool_invocations ADD COLUMN result_tokens INTEGER NOT NULL DEFAULT 0")

    conn.commit()
