"""Block-to-text rendering for conversation dumps.

// [LAW:one-way-deps] Depends on formatting (for block types). No upward deps.
// [LAW:locality-or-seam] Pure data-to-text — no app/widget dependencies.

Hot-reloadable: this module has zero app/widget dependencies.
"""

import cc_dump.core.formatting
from cc_dump.core.analysis import fmt_tokens


def write_block_text(f, block, block_idx: int, log_fn=None) -> None:
    """Write a single block as text to file.

    // [LAW:one-type-per-behavior] Every block type has explicit handler.
    """
    block_type = type(block).__name__
    f.write(f"  [{block_idx}] {block_type}\n")
    f.write(f"  {'-' * 76}\n")

    if isinstance(block, cc_dump.core.formatting.HeaderBlock):
        f.write(f"  {block.label}\n")
        if block.timestamp:
            f.write(f"  Timestamp: {block.timestamp}\n")

    elif isinstance(block, cc_dump.core.formatting.HttpHeadersBlock):
        f.write(f"  {block.header_type.upper()} Headers\n")
        if block.status_code:
            f.write(f"  Status: {block.status_code}\n")
        for key, value in block.headers.items():
            f.write(f"  {key}: {value}\n")

    elif isinstance(block, cc_dump.core.formatting.MetadataBlock):
        if block.model:
            f.write(f"  Model: {block.model}\n")
        if block.max_tokens:
            f.write(f"  Max tokens: {block.max_tokens}\n")
        f.write(f"  Stream: {block.stream}\n")
        if block.tool_count:
            f.write(f"  Tool count: {block.tool_count}\n")

    elif isinstance(block, cc_dump.core.formatting.TrackedContentBlock):
        f.write(f"  Status: {block.status}\n")
        if block.tag_id:
            f.write(f"  Tag ID: {block.tag_id}\n")
        if block.content:
            f.write(f"  Content: {block.content}\n")
        if block.old_content:
            f.write(f"  Old: {block.old_content}\n")
        if block.new_content:
            f.write(f"  New: {block.new_content}\n")

    elif isinstance(block, cc_dump.core.formatting.TextContentBlock):
        if block.content:
            f.write(f"  {block.content}\n")

    elif isinstance(block, cc_dump.core.formatting.ToolUseBlock):
        f.write(f"  Tool: {block.name}\n")
        f.write(f"  ID: {block.tool_use_id}\n")
        if block.detail:
            f.write(f"  Detail: {block.detail}\n")
        if block.input_size:
            f.write(f"  Input lines: {block.input_size}\n")

    elif isinstance(block, cc_dump.core.formatting.ToolResultBlock):
        f.write(f"  Tool: {block.tool_name}\n")
        f.write(f"  ID: {block.tool_use_id}\n")
        if block.detail:
            f.write(f"  Detail: {block.detail}\n")
        if block.is_error:
            f.write(f"  ERROR ({block.size} lines)\n")
        else:
            f.write(f"  Result lines: {block.size}\n")

    elif isinstance(block, cc_dump.core.formatting.ToolUseSummaryBlock):
        f.write("  Tool counts:\n")
        for tool_name, count in block.tool_counts.items():
            f.write(f"    {tool_name}: {count}\n")
        f.write(f"  Total: {block.total}\n")

    elif isinstance(block, cc_dump.core.formatting.ImageBlock):
        f.write(f"  Media type: {block.media_type}\n")

    elif isinstance(block, cc_dump.core.formatting.UnknownTypeBlock):
        f.write(f"  Unknown block type: {block.block_type}\n")

    elif isinstance(block, cc_dump.core.formatting.StreamInfoBlock):
        f.write(f"  Model: {block.model}\n")

    elif isinstance(block, cc_dump.core.formatting.StreamToolUseBlock):
        f.write(f"  Tool: {block.name}\n")

    elif isinstance(block, cc_dump.core.formatting.TextDeltaBlock):
        if block.content:
            f.write(f"  {block.content}\n")

    elif isinstance(block, cc_dump.core.formatting.StopReasonBlock):
        f.write(f"  Stop reason: {block.reason}\n")

    elif isinstance(block, cc_dump.core.formatting.ErrorBlock):
        f.write(f"  Error: {block.code}\n")
        if block.reason:
            f.write(f"  Reason: {block.reason}\n")

    elif isinstance(block, cc_dump.core.formatting.ProxyErrorBlock):
        f.write(f"  Error: {block.error}\n")

    elif isinstance(block, cc_dump.core.formatting.TurnBudgetBlock):
        if block.budget.total_est:
            f.write(f"  total_est: {fmt_tokens(block.budget.total_est)}\n")
        if block.budget.actual_input_tokens:
            f.write(f"  Input tokens: {fmt_tokens(block.budget.actual_input_tokens)}\n")
        if block.budget.actual_output_tokens:
            f.write(f"  Output tokens: {fmt_tokens(block.budget.actual_output_tokens)}\n")
        if block.budget.actual_cache_creation_tokens:
            f.write(f"  Cache creation: {fmt_tokens(block.budget.actual_cache_creation_tokens)}\n")
        if block.budget.actual_cache_read_tokens:
            f.write(f"  Cache read: {fmt_tokens(block.budget.actual_cache_read_tokens)}\n")

    elif isinstance(block, cc_dump.core.formatting.MetadataSection):
        f.write("  METADATA\n")

    elif isinstance(block, cc_dump.core.formatting.ToolDefsSection):
        count = len(getattr(block, "children", []))
        f.write(f"  TOOL DEFINITIONS ({count} tools)\n")

    elif isinstance(block, cc_dump.core.formatting.SystemSection):
        f.write("  SYSTEM\n")

    elif isinstance(block, cc_dump.core.formatting.MessageBlock):
        role = getattr(block, "role", "")
        idx = getattr(block, "msg_index", 0)
        f.write(f"  {role.upper()} [{idx}]\n")
        timestamp = getattr(block, "timestamp", "")
        if timestamp:
            f.write(f"  Timestamp: {timestamp}\n")

    elif isinstance(block, cc_dump.core.formatting.ResponseMetadataSection):
        f.write("  RESPONSE METADATA\n")

    elif isinstance(block, cc_dump.core.formatting.ToolDefBlock):
        f.write(f"  Tool: {block.name}\n")
        if getattr(block, "token_count", 0):
            f.write(f"  Tokens: {fmt_tokens(block.token_count)}\n")

    elif isinstance(block, cc_dump.core.formatting.SkillDefChild):
        f.write(f"  Skill: {block.name}\n")

    elif isinstance(block, cc_dump.core.formatting.AgentDefChild):
        f.write(f"  Agent: {block.name}\n")

    elif isinstance(block, cc_dump.core.formatting.SeparatorBlock):
        f.write(f"  (separator: {block.style})\n")

    elif isinstance(block, cc_dump.core.formatting.NewlineBlock):
        f.write("  (newline)\n")

    else:
        f.write(f"  (unhandled block type: {block_type})\n")
        if log_fn:
            log_fn("WARNING", f"Unhandled block type in dump: {block_type}")
