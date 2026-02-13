"""Conversation dump/export to text file.

// [LAW:one-way-deps] Depends on formatting (for block types). No upward deps.
// [LAW:locality-or-seam] All dump logic here — changes don't touch app.py.

Not hot-reloadable (accesses app widgets and state).
"""

import os
import platform
import subprocess
import tempfile

import cc_dump.formatting


def write_block_text(f, block, block_idx: int, log_fn=None) -> None:
    """Write a single block as text to file.

    // [LAW:one-type-per-behavior] Every block type has explicit handler.
    """
    block_type = type(block).__name__
    f.write(f"  [{block_idx}] {block_type}\n")
    f.write(f"  {'-' * 76}\n")

    if isinstance(block, cc_dump.formatting.HeaderBlock):
        f.write(f"  {block.label}\n")
        if block.timestamp:
            f.write(f"  Timestamp: {block.timestamp}\n")

    elif isinstance(block, cc_dump.formatting.HttpHeadersBlock):
        f.write(f"  {block.header_type.upper()} Headers\n")
        if block.status_code:
            f.write(f"  Status: {block.status_code}\n")
        for key, value in block.headers.items():
            f.write(f"  {key}: {value}\n")

    elif isinstance(block, cc_dump.formatting.MetadataBlock):
        if block.model:
            f.write(f"  Model: {block.model}\n")
        if block.max_tokens:
            f.write(f"  Max tokens: {block.max_tokens}\n")
        f.write(f"  Stream: {block.stream}\n")
        if block.tool_count:
            f.write(f"  Tool count: {block.tool_count}\n")

    elif isinstance(block, cc_dump.formatting.SystemLabelBlock):
        f.write("  SYSTEM:\n")

    elif isinstance(block, cc_dump.formatting.TrackedContentBlock):
        f.write(f"  Status: {block.status}\n")
        if block.tag_id:
            f.write(f"  Tag ID: {block.tag_id}\n")
        if block.content:
            f.write(f"  Content: {block.content}\n")
        if block.old_content:
            f.write(f"  Old: {block.old_content}\n")
        if block.new_content:
            f.write(f"  New: {block.new_content}\n")

    elif isinstance(block, cc_dump.formatting.RoleBlock):
        f.write(f"  Role: {block.role}\n")
        if block.timestamp:
            f.write(f"  Timestamp: {block.timestamp}\n")

    elif isinstance(block, cc_dump.formatting.TextContentBlock):
        if block.text:
            f.write(f"  {block.text}\n")

    elif isinstance(block, cc_dump.formatting.ToolUseBlock):
        f.write(f"  Tool: {block.name}\n")
        f.write(f"  ID: {block.tool_use_id}\n")
        if block.detail:
            f.write(f"  Detail: {block.detail}\n")
        if block.input_size:
            f.write(f"  Input size: {block.input_size} bytes\n")

    elif isinstance(block, cc_dump.formatting.ToolResultBlock):
        f.write(f"  Tool: {block.tool_name}\n")
        f.write(f"  ID: {block.tool_use_id}\n")
        if block.detail:
            f.write(f"  Detail: {block.detail}\n")
        if block.is_error:
            f.write(f"  ERROR (size: {block.size} bytes)\n")
        else:
            f.write(f"  Result size: {block.size} bytes\n")

    elif isinstance(block, cc_dump.formatting.ToolUseSummaryBlock):
        f.write("  Tool counts:\n")
        for tool_name, count in block.tool_counts.items():
            f.write(f"    {tool_name}: {count}\n")
        f.write(f"  Total: {block.total}\n")

    elif isinstance(block, cc_dump.formatting.ImageBlock):
        f.write(f"  Media type: {block.media_type}\n")

    elif isinstance(block, cc_dump.formatting.UnknownTypeBlock):
        f.write(f"  Unknown block type: {block.block_type}\n")

    elif isinstance(block, cc_dump.formatting.StreamInfoBlock):
        f.write(f"  Model: {block.model}\n")

    elif isinstance(block, cc_dump.formatting.StreamToolUseBlock):
        f.write(f"  Tool: {block.name}\n")

    elif isinstance(block, cc_dump.formatting.TextDeltaBlock):
        if block.text:
            f.write(f"  {block.text}\n")

    elif isinstance(block, cc_dump.formatting.StopReasonBlock):
        f.write(f"  Stop reason: {block.reason}\n")

    elif isinstance(block, cc_dump.formatting.ErrorBlock):
        f.write(f"  Error: {block.code}\n")
        if block.reason:
            f.write(f"  Reason: {block.reason}\n")

    elif isinstance(block, cc_dump.formatting.ProxyErrorBlock):
        f.write(f"  Error: {block.error}\n")

    elif isinstance(block, cc_dump.formatting.TurnBudgetBlock):
        if block.budget.total_est:
            f.write(f"  total_est: {block.budget.total_est}\n")
        if block.budget.actual_input_tokens:
            f.write(f"  Input tokens: {block.budget.actual_input_tokens}\n")
        if block.budget.actual_output_tokens:
            f.write(f"  Output tokens: {block.budget.actual_output_tokens}\n")
        if block.budget.actual_cache_creation_tokens:
            f.write(f"  Cache creation: {block.budget.actual_cache_creation_tokens}\n")
        if block.budget.actual_cache_read_tokens:
            f.write(f"  Cache read: {block.budget.actual_cache_read_tokens}\n")

    elif isinstance(block, cc_dump.formatting.SeparatorBlock):
        f.write(f"  (separator: {block.style})\n")

    elif isinstance(block, cc_dump.formatting.NewlineBlock):
        f.write("  (newline)\n")

    else:
        f.write(f"  (unhandled block type: {block_type})\n")
        if log_fn:
            log_fn("WARNING", f"Unhandled block type in dump: {block_type}")


def dump_conversation(app) -> None:
    """Dump entire conversation to a temp file and optionally open in $VISUAL.

    // [LAW:dataflow-not-control-flow] Always create file; vary behavior via platform/env.
    """
    conv = app._get_conv()
    if conv is None or not conv._turns:
        app._app_log("WARNING", "No conversation data to dump")
        app.znotify("No conversation to dump", severity="warning")
        return

    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="cc-dump-")

        with os.fdopen(fd, "w") as f:
            f.write("=" * 80 + "\n")
            f.write("CC-DUMP CONVERSATION EXPORT\n")
            f.write("=" * 80 + "\n\n")

            for turn_idx, turn_data in enumerate(conv._turns):
                f.write(f"\n{'─' * 80}\n")
                f.write(f"TURN {turn_idx + 1}\n")
                f.write(f"{'─' * 80}\n\n")

                for block_idx, block in enumerate(turn_data.blocks):
                    write_block_text(f, block, block_idx, log_fn=app._app_log)
                    f.write("\n")

        app._app_log("INFO", f"Conversation dumped to: {tmp_path}")
        app.notify(f"Exported to: {tmp_path}")

        # On macOS with $VISUAL, open the file
        if platform.system() == "Darwin" and os.environ.get("VISUAL"):
            editor = os.environ["VISUAL"]
            app._app_log("INFO", f"Opening in $VISUAL ({editor})...")
            app.notify(f"Opening in {editor}...")

            try:
                result = subprocess.run(
                    [editor, tmp_path], timeout=20, capture_output=True, text=True
                )
                if result.returncode == 0:
                    app._app_log("INFO", "Editor opened successfully")
                else:
                    app._app_log("WARNING", f"Editor exited with code {result.returncode}")
            except subprocess.TimeoutExpired:
                app._app_log(
                    "WARNING",
                    "Editor timeout after 20s (still running in background)",
                )
                app.notify("Editor timeout (still open)", severity="warning")
            except Exception as e:
                app._app_log("ERROR", f"Failed to open editor: {e}")
                app.notify(f"Editor error: {e}", severity="error")

    except Exception as e:
        app._app_log("ERROR", f"Failed to dump conversation: {e}")
        app.notify(f"Dump failed: {e}", severity="error")
