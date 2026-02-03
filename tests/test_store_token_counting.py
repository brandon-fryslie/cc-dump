"""Integration tests for token counting in store.py."""

import tempfile
import os
import sqlite3
from cc_dump.store import SQLiteWriter


def test_store_populates_token_counts():
    """End-to-end test: request with tool use → commit → verify token counts in DB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        writer = SQLiteWriter(db_path, "test-session")

        # Simulate a request with a tool use
        request = {
            "model": "claude-3-sonnet-20240229",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_abc123",
                            "name": "Read",
                            "input": {"file_path": "/path/to/file.txt"}
                        }
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_abc123",
                            "content": "This is the file content with multiple words that will be tokenized."
                        }
                    ]
                }
            ]
        }

        # Simulate the event sequence
        writer.on_event(("request", request))
        writer.on_event(("response_event", "message_start", {
            "message": {
                "model": "claude-3-sonnet-20240229",
                "usage": {"input_tokens": 100, "output_tokens": 0}
            }
        }))
        writer.on_event(("response_event", "message_delta", {
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 50}
        }))
        writer.on_event(("response_done",))

        # Query the database to verify token counts
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("""
            SELECT tool_name, input_bytes, result_bytes, input_tokens, result_tokens
            FROM tool_invocations
        """)
        rows = cursor.fetchall()

        assert len(rows) == 1, f"Expected 1 tool invocation, got {len(rows)}"

        tool_name, input_bytes, result_bytes, input_tokens, result_tokens = rows[0]

        # Verify basic fields
        assert tool_name == "Read"
        assert input_bytes > 0
        assert result_bytes > 0

        # Verify token counts are non-zero and reasonable
        assert input_tokens > 0, "input_tokens should be non-zero"
        assert result_tokens > 0, "result_tokens should be non-zero"

        # Token counts should be smaller than byte counts (tokens compress)
        assert input_tokens < input_bytes, "tokens should be fewer than bytes"
        assert result_tokens < result_bytes, "tokens should be fewer than bytes"

        # Specific expectations based on the input
        # Input: {"file_path": "/path/to/file.txt"} ~6-10 tokens
        assert 3 <= input_tokens <= 15, f"Expected ~6-10 input tokens, got {input_tokens}"

        # Result: "This is the file content..." ~14-20 tokens
        assert 10 <= result_tokens <= 25, f"Expected ~14-20 result tokens, got {result_tokens}"

        conn.close()


def test_store_handles_empty_tool_inputs():
    """Token counting handles empty/minimal strings gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        writer = SQLiteWriter(db_path, "test-session")

        # Tool with minimal input and empty result
        request = {
            "model": "claude-3-sonnet-20240229",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_xyz",
                            "name": "Bash",
                            "input": {}  # Empty dict → "{}" → 1 token
                        }
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_xyz",
                            "content": ""  # Empty string → 0 tokens
                        }
                    ]
                }
            ]
        }

        writer.on_event(("request", request))
        writer.on_event(("response_event", "message_start", {
            "message": {"model": "claude-3-sonnet-20240229", "usage": {}}
        }))
        writer.on_event(("response_done",))

        # Query database
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT input_tokens, result_tokens FROM tool_invocations")
        row = cursor.fetchone()

        # Empty dict "{}" tokenizes to ~1 token
        assert row[0] >= 0, "Empty input should have minimal tokens"
        # Empty string should give 0 tokens
        assert row[1] == 0, "Empty result should have 0 tokens"

        conn.close()


def test_store_handles_multiple_tools():
    """Token counting works for multiple tool invocations in one turn."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        writer = SQLiteWriter(db_path, "test-session")

        request = {
            "model": "claude-3-sonnet-20240229",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "Read",
                            "input": {"file": "a.txt"}
                        },
                        {
                            "type": "tool_use",
                            "id": "tool_2",
                            "name": "Write",
                            "input": {"file": "b.txt", "content": "hello world"}
                        }
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_1",
                            "content": "short"
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_2",
                            "content": "longer result with more text"
                        }
                    ]
                }
            ]
        }

        writer.on_event(("request", request))
        writer.on_event(("response_event", "message_start", {
            "message": {"model": "claude-3-sonnet-20240229", "usage": {}}
        }))
        writer.on_event(("response_done",))

        # Query database
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("""
            SELECT tool_name, input_tokens, result_tokens
            FROM tool_invocations
            ORDER BY tool_name
        """)
        rows = cursor.fetchall()

        assert len(rows) == 2, f"Expected 2 tool invocations, got {len(rows)}"

        # Read tool
        assert rows[0][0] == "Read"
        assert rows[0][1] > 0  # input tokens
        assert rows[0][2] > 0  # result tokens

        # Write tool
        assert rows[1][0] == "Write"
        assert rows[1][1] > 0  # input tokens (should be more than Read due to content)
        assert rows[1][2] > 0  # result tokens

        # Write tool should have more input tokens (has content field)
        assert rows[1][1] > rows[0][1], "Write tool should have more input tokens"

        conn.close()
