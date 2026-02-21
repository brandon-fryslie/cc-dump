"""Conversation dump/export to text file.

// [LAW:one-way-deps] Depends on dump_formatting (for block rendering). No upward deps.
// [LAW:locality-or-seam] All dump logic here — changes don't touch app.py.

Hot-reloadable — imported as module object in app.py, delegates to dump_formatting.
"""

import os
import platform
import subprocess
import tempfile

import cc_dump.tui.dump_formatting


def write_block_text(f, block, block_idx: int, log_fn=None) -> None:
    """Delegate to hot-reloadable dump_formatting module."""
    cc_dump.tui.dump_formatting.write_block_text(f, block, block_idx, log_fn)


def dump_conversation(app) -> None:
    """Dump entire conversation to a temp file and optionally open in $VISUAL.

    // [LAW:dataflow-not-control-flow] Always create file; vary behavior via platform/env.
    """
    conv = app._get_conv()
    if conv is None or not conv._turns:
        app._app_log("WARNING", "No conversation data to dump")
        app.notify("No conversation to dump", severity="warning")
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

                block_counter = [0]  # mutable counter for nested blocks
                def _dump_blocks(blocks):
                    for block in blocks:
                        write_block_text(f, block, block_counter[0], log_fn=app._app_log)
                        f.write("\n")
                        block_counter[0] += 1
                        _dump_blocks(getattr(block, "children", []))
                _dump_blocks(turn_data.blocks)

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
