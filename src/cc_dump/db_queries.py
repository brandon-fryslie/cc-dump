"""Read-only database query layer for TUI panels.

This module provides pure query functions that read from the SQLite database
to populate TUI panels. All queries use read-only connections for thread safety.

This module is hot-reloadable - it can be edited while the TUI is running.
"""

import sqlite3
from typing import Optional

from cc_dump.analysis import ToolInvocation, estimate_tokens


def get_session_stats(db_path: str, session_id: str, current_turn: Optional[dict] = None) -> dict:
    """Query cumulative token counts for a session.

    Args:
        db_path: Path to SQLite database
        session_id: Session identifier
        current_turn: Optional dict with in-progress turn data to merge
                     Expected keys: input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens

    Returns:
        Dict with keys:
            - input_tokens: Cumulative fresh input tokens
            - output_tokens: Cumulative output tokens
            - cache_read_tokens: Cumulative cache read tokens
            - cache_creation_tokens: Cumulative cache creation tokens
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.execute("""
            SELECT
                SUM(input_tokens) as total_input,
                SUM(output_tokens) as total_output,
                SUM(cache_read_tokens) as total_cache_read,
                SUM(cache_creation_tokens) as total_cache_creation
            FROM turns
            WHERE session_id = ?
        """, (session_id,))

        row = cursor.fetchone()

        # Handle case where no turns exist yet
        stats = {
            "input_tokens": row[0] or 0,
            "output_tokens": row[1] or 0,
            "cache_read_tokens": row[2] or 0,
            "cache_creation_tokens": row[3] or 0,
        }

        # Merge current incomplete turn if provided
        if current_turn:
            stats["input_tokens"] += current_turn.get("input_tokens", 0)
            stats["output_tokens"] += current_turn.get("output_tokens", 0)
            stats["cache_read_tokens"] += current_turn.get("cache_read_tokens", 0)
            stats["cache_creation_tokens"] += current_turn.get("cache_creation_tokens", 0)

        return stats
    finally:
        conn.close()


def get_tool_invocations(db_path: str, session_id: str) -> list[ToolInvocation]:
    """Query all tool invocations for a session.

    Args:
        db_path: Path to SQLite database
        session_id: Session identifier

    Returns:
        List of ToolInvocation objects with token estimates
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.execute("""
            SELECT
                ti.tool_name,
                ti.tool_use_id,
                ti.input_bytes,
                ti.result_bytes,
                ti.is_error
            FROM tool_invocations ti
            JOIN turns t ON ti.turn_id = t.id
            WHERE t.session_id = ?
            ORDER BY ti.id
        """, (session_id,))

        invocations = []
        for row in cursor:
            tool_name, tool_use_id, input_bytes, result_bytes, is_error = row

            # Estimate tokens from bytes (using same heuristic as analysis module)
            invocations.append(ToolInvocation(
                tool_use_id=tool_use_id,
                name=tool_name,
                input_bytes=input_bytes,
                result_bytes=result_bytes,
                input_tokens_est=estimate_tokens("x" * input_bytes),
                result_tokens_est=estimate_tokens("x" * result_bytes),
                is_error=bool(is_error),
            ))

        return invocations
    finally:
        conn.close()


def get_turn_timeline(db_path: str, session_id: str) -> list[dict]:
    """Query turn timeline data for a session.

    Args:
        db_path: Path to SQLite database
        session_id: Session identifier

    Returns:
        List of dicts with keys:
            - sequence_num: Turn number (1-indexed)
            - input_tokens: Fresh input tokens
            - output_tokens: Output tokens
            - cache_read_tokens: Cache read tokens
            - cache_creation_tokens: Cache creation tokens
            - request_json: JSON string of request body (for budget calculation)
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.execute("""
            SELECT
                sequence_num,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_creation_tokens,
                request_json
            FROM turns
            WHERE session_id = ?
            ORDER BY sequence_num
        """, (session_id,))

        timeline = []
        for row in cursor:
            timeline.append({
                "sequence_num": row[0],
                "input_tokens": row[1],
                "output_tokens": row[2],
                "cache_read_tokens": row[3],
                "cache_creation_tokens": row[4],
                "request_json": row[5],
            })

        return timeline
    finally:
        conn.close()
