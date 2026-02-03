"""Tests for schema initialization and migration."""

import sqlite3
import tempfile
import os
from cc_dump.schema import init_db, SCHEMA_VERSION, _migrate_v2_to_v3


def test_schema_version():
    """Schema version is 3."""
    assert SCHEMA_VERSION == 3


def test_fresh_database_has_token_columns():
    """New databases get input_tokens and result_tokens columns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = init_db(db_path)

        # Check table schema
        cursor = conn.execute("PRAGMA table_info(tool_invocations)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}  # name: type

        assert "input_tokens" in columns
        assert "result_tokens" in columns
        assert columns["input_tokens"] == "INTEGER"
        assert columns["result_tokens"] == "INTEGER"

        conn.close()


def test_migration_adds_token_columns():
    """Existing v2 databases get token columns added via migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)

        # Create v2 schema (without token columns)
        conn.executescript("""
            CREATE TABLE tool_invocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                tool_use_id TEXT NOT NULL,
                input_bytes INTEGER NOT NULL DEFAULT 0,
                result_bytes INTEGER NOT NULL DEFAULT 0,
                is_error INTEGER NOT NULL DEFAULT 0
            );
        """)

        # Insert test data
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, is_error)
            VALUES (1, 'Read', 'tool_123', 100, 200, 0)
        """)
        conn.commit()

        # Verify columns don't exist yet
        cursor = conn.execute("PRAGMA table_info(tool_invocations)")
        columns_before = {row[1] for row in cursor.fetchall()}
        assert "input_tokens" not in columns_before
        assert "result_tokens" not in columns_before

        # Run migration
        _migrate_v2_to_v3(conn)

        # Verify columns were added
        cursor = conn.execute("PRAGMA table_info(tool_invocations)")
        columns_after = {row[1]: row for row in cursor.fetchall()}
        assert "input_tokens" in columns_after
        assert "result_tokens" in columns_after

        # Verify existing data is preserved
        cursor = conn.execute("SELECT tool_name, input_bytes, result_bytes, input_tokens, result_tokens FROM tool_invocations")
        row = cursor.fetchone()
        assert row[0] == "Read"
        assert row[1] == 100  # input_bytes preserved
        assert row[2] == 200  # result_bytes preserved
        assert row[3] == 0    # input_tokens defaulted to 0
        assert row[4] == 0    # result_tokens defaulted to 0

        conn.close()


def test_migration_is_idempotent():
    """Running migration multiple times doesn't break anything."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = init_db(db_path)

        # Run migration again (init_db already ran it once)
        _migrate_v2_to_v3(conn)
        _migrate_v2_to_v3(conn)

        # Verify columns still exist and table is functional
        cursor = conn.execute("PRAGMA table_info(tool_invocations)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "input_tokens" in columns
        assert "result_tokens" in columns

        # Verify we can insert data
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (1, 'Write', 'tool_456', 50, 100, 10, 20, 0)
        """)
        conn.commit()

        cursor = conn.execute("SELECT input_tokens, result_tokens FROM tool_invocations WHERE tool_use_id = 'tool_456'")
        row = cursor.fetchone()
        assert row[0] == 10
        assert row[1] == 20

        conn.close()
