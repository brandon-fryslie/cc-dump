"""Block-to-text rendering for conversation dumps.

// [LAW:one-way-deps] Depends on formatting (for block types). No upward deps.
// [LAW:locality-or-seam] Pure data-to-text — no app/widget dependencies.

Hot-reloadable: this module has zero app/widget dependencies.
"""

from collections.abc import Callable
from typing import TextIO

import cc_dump.core.formatting as fmt
from cc_dump.core.analysis import fmt_tokens


BlockWriter = Callable[[TextIO, object], None]


def _write_header(f: TextIO, block: object, block_idx: int) -> None:
    block_type = type(block).__name__
    f.write(f"  [{block_idx}] {block_type}\n")
    f.write(f"  {'-' * 76}\n")


def _write_header_block(f: TextIO, block: fmt.HeaderBlock) -> None:
    f.write(f"  {block.label}\n")
    if block.timestamp:
        f.write(f"  Timestamp: {block.timestamp}\n")


def _write_http_headers_block(f: TextIO, block: fmt.HttpHeadersBlock) -> None:
    f.write(f"  {block.header_type.upper()} Headers\n")
    if block.status_code:
        f.write(f"  Status: {block.status_code}\n")
    for key, value in block.headers.items():
        f.write(f"  {key}: {value}\n")


def _write_metadata_block(f: TextIO, block: fmt.MetadataBlock) -> None:
    if block.model:
        f.write(f"  Model: {block.model}\n")
    if block.max_tokens:
        f.write(f"  Max tokens: {block.max_tokens}\n")
    f.write(f"  Stream: {block.stream}\n")
    if block.tool_count:
        f.write(f"  Tool count: {block.tool_count}\n")


def _write_text_content_block(f: TextIO, block: fmt.TextContentBlock) -> None:
    if block.content:
        f.write(f"  {block.content}\n")


def _write_tool_use_block(f: TextIO, block: fmt.ToolUseBlock) -> None:
    f.write(f"  Tool: {block.name}\n")
    f.write(f"  ID: {block.tool_use_id}\n")
    if block.detail:
        f.write(f"  Detail: {block.detail}\n")
    if block.input_size:
        f.write(f"  Input lines: {block.input_size}\n")


def _write_tool_result_block(f: TextIO, block: fmt.ToolResultBlock) -> None:
    f.write(f"  Tool: {block.tool_name}\n")
    f.write(f"  ID: {block.tool_use_id}\n")
    if block.detail:
        f.write(f"  Detail: {block.detail}\n")
    if block.is_error:
        f.write(f"  ERROR ({block.size} lines)\n")
    else:
        f.write(f"  Result lines: {block.size}\n")


def _write_tool_use_summary_block(f: TextIO, block: fmt.ToolUseSummaryBlock) -> None:
    f.write("  Tool counts:\n")
    for tool_name, count in block.tool_counts.items():
        f.write(f"    {tool_name}: {count}\n")
    f.write(f"  Total: {block.total}\n")


def _write_image_block(f: TextIO, block: fmt.ImageBlock) -> None:
    f.write(f"  Media type: {block.media_type}\n")


def _write_unknown_type_block(f: TextIO, block: fmt.UnknownTypeBlock) -> None:
    f.write(f"  Unknown block type: {block.block_type}\n")


def _write_stream_info_block(f: TextIO, block: fmt.StreamInfoBlock) -> None:
    f.write(f"  Model: {block.model}\n")


def _write_stream_tool_use_block(f: TextIO, block: fmt.StreamToolUseBlock) -> None:
    f.write(f"  Tool: {block.name}\n")


def _write_text_delta_block(f: TextIO, block: fmt.TextDeltaBlock) -> None:
    if block.content:
        f.write(f"  {block.content}\n")


def _write_stop_reason_block(f: TextIO, block: fmt.StopReasonBlock) -> None:
    f.write(f"  Stop reason: {block.reason}\n")


def _write_response_usage_block(f: TextIO, block: fmt.ResponseUsageBlock) -> None:
    total_in = block.input_tokens + block.cache_read_tokens
    f.write(f"  Usage: {total_in} in → {block.output_tokens} out")
    if block.cache_read_tokens > 0:
        f.write(f" (cache_read: {block.cache_read_tokens}")
        if block.cache_creation_tokens > 0:
            f.write(f", cache_creation: {block.cache_creation_tokens}")
        f.write(")")
    f.write("\n")


def _write_error_block(f: TextIO, block: fmt.ErrorBlock) -> None:
    f.write(f"  Error: {block.code}\n")
    if block.reason:
        f.write(f"  Reason: {block.reason}\n")


def _write_proxy_error_block(f: TextIO, block: fmt.ProxyErrorBlock) -> None:
    f.write(f"  Error: {block.error}\n")


def _write_turn_budget_block(f: TextIO, block: fmt.TurnBudgetBlock) -> None:
    budget = block.budget
    if budget.total_est:
        f.write(f"  total_est: {fmt_tokens(budget.total_est)}\n")
    if budget.actual_input_tokens:
        f.write(f"  Input tokens: {fmt_tokens(budget.actual_input_tokens)}\n")
    if budget.actual_output_tokens:
        f.write(f"  Output tokens: {fmt_tokens(budget.actual_output_tokens)}\n")
    if budget.actual_cache_creation_tokens:
        f.write(f"  Cache creation: {fmt_tokens(budget.actual_cache_creation_tokens)}\n")
    if budget.actual_cache_read_tokens:
        f.write(f"  Cache read: {fmt_tokens(budget.actual_cache_read_tokens)}\n")


def _write_metadata_section(f: TextIO, block: fmt.MetadataSection) -> None:
    _ = block
    f.write("  METADATA\n")


def _write_tool_defs_section(f: TextIO, block: fmt.ToolDefsSection) -> None:
    count = len(getattr(block, "children", []))
    f.write(f"  TOOL DEFINITIONS ({count} tools)\n")


def _write_system_section(f: TextIO, block: fmt.SystemSection) -> None:
    _ = block
    f.write("  SYSTEM\n")


def _write_message_block(f: TextIO, block: fmt.MessageBlock) -> None:
    role = getattr(block, "role", "")
    idx = getattr(block, "msg_index", 0)
    f.write(f"  {role.upper()} [{idx}]\n")
    timestamp = getattr(block, "timestamp", "")
    if timestamp:
        f.write(f"  Timestamp: {timestamp}\n")


def _write_response_metadata_section(
    f: TextIO,
    block: fmt.ResponseMetadataSection,
) -> None:
    _ = block
    f.write("  RESPONSE METADATA\n")


def _write_tool_def_block(f: TextIO, block: fmt.ToolDefBlock) -> None:
    f.write(f"  Tool: {block.name}\n")
    if getattr(block, "token_count", 0):
        f.write(f"  Tokens: {fmt_tokens(block.token_count)}\n")


def _write_skill_def_child(f: TextIO, block: fmt.SkillDefChild) -> None:
    f.write(f"  Skill: {block.name}\n")


def _write_agent_def_child(f: TextIO, block: fmt.AgentDefChild) -> None:
    f.write(f"  Agent: {block.name}\n")


def _write_separator_block(f: TextIO, block: fmt.SeparatorBlock) -> None:
    f.write(f"  (separator: {block.style})\n")


def _write_newline_block(f: TextIO, block: fmt.NewlineBlock) -> None:
    _ = block
    f.write("  (newline)\n")


# // [LAW:one-source-of-truth] Block type dispatch is defined exactly once.
BLOCK_WRITERS: dict[type[object], BlockWriter] = {
    fmt.HeaderBlock: _write_header_block,
    fmt.HttpHeadersBlock: _write_http_headers_block,
    fmt.MetadataBlock: _write_metadata_block,
    fmt.TextContentBlock: _write_text_content_block,
    fmt.ToolUseBlock: _write_tool_use_block,
    fmt.ToolResultBlock: _write_tool_result_block,
    fmt.ToolUseSummaryBlock: _write_tool_use_summary_block,
    fmt.ImageBlock: _write_image_block,
    fmt.UnknownTypeBlock: _write_unknown_type_block,
    fmt.StreamInfoBlock: _write_stream_info_block,
    fmt.StreamToolUseBlock: _write_stream_tool_use_block,
    fmt.TextDeltaBlock: _write_text_delta_block,
    fmt.StopReasonBlock: _write_stop_reason_block,
    fmt.ResponseUsageBlock: _write_response_usage_block,
    fmt.ErrorBlock: _write_error_block,
    fmt.ProxyErrorBlock: _write_proxy_error_block,
    fmt.TurnBudgetBlock: _write_turn_budget_block,
    fmt.MetadataSection: _write_metadata_section,
    fmt.ToolDefsSection: _write_tool_defs_section,
    fmt.SystemSection: _write_system_section,
    fmt.MessageBlock: _write_message_block,
    fmt.ResponseMetadataSection: _write_response_metadata_section,
    fmt.ToolDefBlock: _write_tool_def_block,
    fmt.SkillDefChild: _write_skill_def_child,
    fmt.AgentDefChild: _write_agent_def_child,
    fmt.SeparatorBlock: _write_separator_block,
    fmt.NewlineBlock: _write_newline_block,
}


def write_block_text(f, block, block_idx: int, log_fn=None) -> None:
    """Write a single block as text to file.

    // [LAW:one-type-per-behavior] Every block type maps to one handler type.
    // [LAW:dataflow-not-control-flow] Dispatch is data-driven via BLOCK_WRITERS.
    """
    _write_header(f, block, block_idx)
    handler = BLOCK_WRITERS.get(type(block))
    if handler is not None:
        handler(f, block)
        return

    block_type = type(block).__name__
    f.write(f"  (unhandled block type: {block_type})\n")
    if log_fn:
        log_fn("WARNING", f"Unhandled block type in dump: {block_type}")
