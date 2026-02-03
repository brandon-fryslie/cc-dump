"""Read-only database query layer for TUI panels.

This module provides pure query functions that read from the SQLite database
to populate TUI panels. All queries use read-only connections for thread safety.

This module is hot-reloadable - it can be edited while the TUI is running.
"""

import sqlite3
from typing import Optional

from cc_dump.analysis import ToolInvocation, ToolEconomicsRow, classify_model, HAIKU_BASE_UNIT, estimate_tokens


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


def get_tool_economics(db_path: str, session_id: str) -> list[ToolEconomicsRow]:
    """Query per-tool economics with real token counts and cache attribution.

    Returns list of ToolEconomicsRow with:
    - Real token counts from tool_invocations (input_tokens, result_tokens)
    - Proportional cache attribution from parent turn
    - Normalized cost using model pricing
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        # Fetch per-invocation data with turn-level context
        cursor = conn.execute("""
            SELECT
                ti.tool_name,
                ti.input_tokens,
                ti.result_tokens,
                t.model,
                t.input_tokens as turn_input,
                t.cache_read_tokens as turn_cache_read,
                t.id as turn_id
            FROM tool_invocations ti
            JOIN turns t ON ti.turn_id = t.id
            WHERE t.session_id = ?
            ORDER BY ti.id
        """, (session_id,))

        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    # Compute per-turn total tool input tokens (for proportional cache attribution)
    turn_tool_totals = {}  # turn_id -> sum of tool input_tokens
    for tool_name, input_tokens, result_tokens, model, turn_input, turn_cache_read, turn_id in rows:
        turn_tool_totals[turn_id] = turn_tool_totals.get(turn_id, 0) + input_tokens

    # Aggregate by tool name
    by_name = {}  # tool_name -> {calls, input_tokens, result_tokens, cache_read, cost_sum}
    for tool_name, input_tokens, result_tokens, model, turn_input, turn_cache_read, turn_id in rows:
        if tool_name not in by_name:
            by_name[tool_name] = {
                "calls": 0, "input_tokens": 0, "result_tokens": 0,
                "cache_read": 0, "norm_cost": 0.0,
            }
        agg = by_name[tool_name]
        agg["calls"] += 1
        agg["input_tokens"] += input_tokens
        agg["result_tokens"] += result_tokens

        # Proportional cache attribution
        turn_total = turn_tool_totals.get(turn_id, 0)
        if turn_total > 0 and turn_cache_read > 0:
            share = input_tokens / turn_total
            agg["cache_read"] += int(turn_cache_read * share)

        # Norm cost contribution
        _, pricing = classify_model(model)
        agg["norm_cost"] += (
            input_tokens * (pricing.base_input / HAIKU_BASE_UNIT)
            + result_tokens * (pricing.output / HAIKU_BASE_UNIT)
        )

    # Build result list sorted by norm_cost descending
    result = []
    for name, agg in sorted(by_name.items(), key=lambda x: x[1]["norm_cost"], reverse=True):
        result.append(ToolEconomicsRow(
            name=name,
            calls=agg["calls"],
            input_tokens=agg["input_tokens"],
            result_tokens=agg["result_tokens"],
            cache_read_tokens=agg["cache_read"],
            norm_cost=agg["norm_cost"],
        ))

    return result


def get_model_economics(db_path: str, session_id: str) -> list[dict]:
    """Query per-model aggregated token data for a session.

    Returns list of dicts with keys: model, calls, input_tokens,
    output_tokens, cache_read_tokens, cache_creation_tokens.
    Grouped by model, ordered by total input descending.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.execute("""
            SELECT
                model,
                COUNT(*) as calls,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cache_read_tokens) as cache_read_tokens,
                SUM(cache_creation_tokens) as cache_creation_tokens
            FROM turns
            WHERE session_id = ?
            GROUP BY model
            ORDER BY SUM(input_tokens + cache_read_tokens) DESC
        """, (session_id,))

        results = []
        for row in cursor:
            results.append({
                "model": row[0] or "",
                "calls": row[1],
                "input_tokens": row[2] or 0,
                "output_tokens": row[3] or 0,
                "cache_read_tokens": row[4] or 0,
                "cache_creation_tokens": row[5] or 0,
            })
        return results
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
