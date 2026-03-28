# Export

## Overview

When a user is deep in a cc-dump session watching Claude Code traffic, they often need to capture what they've seen for later analysis, sharing, or filing a bug report. The conversation data is transient -- it lives in the TUI's memory and will be gone when the process exits. Export solves this by dumping the entire conversation to a plain-text file that preserves the structural information (turns, block types, metadata) without requiring cc-dump to read it back.

Export produces a human-readable text file from the current conversation state. It writes to a temporary file and optionally opens it in the user's editor. There is currently one format (plain text) and one trigger (the command palette).

## Trigger

Export is invoked via the Textual command palette as "Dump conversation" (`action_dump_conversation`). There is no dedicated keybinding. The action is registered as a `SystemCommand` in `get_system_commands()` with the title "Dump conversation" and description "Export conversation to text file".

## Output Format

The export format is plain text (`.txt`), structured with visual separators:

```
================================================================================
CC-DUMP CONVERSATION EXPORT
================================================================================


────────────────────────────────────────────────────────────────────────────────
TURN 1
────────────────────────────────────────────────────────────────────────────────

  [0] HeaderBlock
  --------------------------------------------------------------------------
  <header label>
  Timestamp: <timestamp>

  [1] MetadataBlock
  --------------------------------------------------------------------------
  Model: claude-sonnet-4-20250514
  Max tokens: 16384
  Stream: True
  Tool count: 42

  ...
```

### Block rendering

Each block is rendered with:
1. A header line showing the block index (zero-based within the turn) and the block type name (Python class name)
2. A separator line (76 dashes, indented 2 spaces)
3. Block-specific content, indented 2 spaces

Children of hierarchical blocks (e.g., children of `ToolDefsSection`) are rendered recursively with the same format, sharing a turn-level block counter (a mutable `[0]` list incremented after each block).

### Block types and their text output

| Block Type | Fields Written |
|---|---|
| `HeaderBlock` | `label`, `timestamp` (if present) |
| `HttpHeadersBlock` | `header_type` (uppercased, suffixed with " Headers"), `status_code` (if present, labeled "Status"), all `headers` as key-value pairs |
| `MetadataBlock` | `model`, `max_tokens`, `stream` (always written), `tool_count` (each if present) |
| `TextContentBlock` | `content` (if present) |
| `ToolUseBlock` | `name` (labeled "Tool"), `tool_use_id` (labeled "ID"), `detail` (if present), `input_size` (if present, labeled "Input lines") |
| `ToolResultBlock` | `tool_name` (labeled "Tool"), `tool_use_id` (labeled "ID"), `detail` (if present), error status with `size` (labeled "ERROR (N lines)"), or `size` as "Result lines" |
| `ToolUseSummaryBlock` | "Tool counts:" header, per-tool name:count pairs (indented 4 spaces), `total` |
| `ImageBlock` | `media_type` (labeled "Media type") |
| `UnknownTypeBlock` | `block_type` (labeled "Unknown block type") |
| `StreamInfoBlock` | `model` (labeled "Model") |
| `StreamToolUseBlock` | `name` (labeled "Tool") |
| `TextDeltaBlock` | `content` (if present) |
| `StopReasonBlock` | `reason` (labeled "Stop reason") |
| `ResponseUsageBlock` | Total input tokens (input + cache_read + cache_creation) and output tokens formatted as "Usage: N in -> N out", with cache breakdown parenthetical if cache tokens > 0 |
| `ErrorBlock` | `code` (labeled "Error"), `reason` (if present, labeled "Reason") |
| `ProxyErrorBlock` | `error` (labeled "Error") |
| `TurnBudgetBlock` | Reads from `block.budget` sub-object: `total_est`, `actual_input_tokens`, `actual_output_tokens`, `actual_cache_creation_tokens`, `actual_cache_read_tokens` (each if present, formatted via `fmt_tokens`) |
| `MetadataSection` | Label "METADATA" |
| `ToolDefsSection` | Label "TOOL DEFINITIONS (N tools)" where N is `len(block.children)` |
| `SystemSection` | Label "SYSTEM" |
| `MessageBlock` | `role` (uppercased) with `msg_index` in brackets, `timestamp` (if present) |
| `ResponseMetadataSection` | Label "RESPONSE METADATA" |
| `ToolDefBlock` | `name` (labeled "Tool"), `token_count` (if present and truthy, formatted via `fmt_tokens`, labeled "Tokens") |
| `SkillDefChild` | `name` (labeled "Skill") |
| `AgentDefChild` | `name` (labeled "Agent") |
| `SeparatorBlock` | Label "(separator: <style>)" |
| `NewlineBlock` | Label "(newline)" |

Unhandled block types produce `(unhandled block type: <TypeName>)` and log a warning via the optional `log_fn` callback.

### Dispatch mechanism

Block type dispatch is data-driven via the `BLOCK_WRITERS` dictionary in `dump_formatting.py`, keyed by block type class. Each value is a callable `(TextIO, block) -> None`. The `write_block_text` function writes the header, then looks up and calls the handler, falling back to the unhandled-type message.

## File Output

- **Location:** System temp directory via `tempfile.mkstemp`, with prefix `cc-dump-` and suffix `.txt`
- **Encoding:** Written via `os.fdopen(fd, "w")` using the system default encoding
- **Notification:** The file path is shown via Textual's `notify()` (default severity) and logged at INFO level

## Editor Integration

On macOS (`platform.system() == "Darwin"`), if the `$VISUAL` environment variable is set, cc-dump attempts to open the exported file in that editor. This is a deliberate scope choice -- macOS is the primary development platform for cc-dump, and `$VISUAL` is the standard Unix convention for the user's preferred visual editor.

- The editor command is invoked as `[$VISUAL, <path>]` via `subprocess.run` with `capture_output=True` and `text=True`
- A second `notify()` call informs the user the editor is being opened
- **Timeout:** 20 seconds. If the editor hasn't exited by then, cc-dump logs a warning ("Editor timeout after 20s (still running in background)") and shows a warning notification ("Editor timeout (still open)"). This timeout accommodates GUI editors like `open` or `code` that return quickly, while not blocking indefinitely on terminal editors.
- **Success:** Exit code 0 is logged at INFO level ("Editor opened successfully"). No user-facing notification beyond the initial "Opening in..." one.
- **Failure handling:** Non-zero exit codes are logged as warnings. Exceptions are logged as errors and shown via `notify()` with error severity.

On non-macOS platforms, or when `$VISUAL` is not set, the file is created but no editor is opened. The user must navigate to the temp path shown in the notification.

## Edge Cases

- **Empty conversation:** If `app._get_conv()` returns `None` or the conversation has no turns, export logs a WARNING ("No conversation data to dump"), shows a warning notification ("No conversation to dump"), and does not create a file.
- **Write failure:** Any exception during file creation or writing is caught, logged as ERROR, and shown via `notify()` with error severity.
- **File cleanup:** Temp files are not automatically cleaned up. They persist until the OS cleans the temp directory or the user deletes them.

## What Is Not Exported

- Visibility state (which blocks are expanded/collapsed)
- Rendering styles or colors
- Scroll position or follow-mode state
- Search highlights
- Error indicator overlay state
- HAR recording data (that is a separate system)

## Hot Reload

Both `dump_export` and `dump_formatting` are hot-reloadable modules. The `dump_export` module delegates to `dump_formatting` via module-level import (`import cc_dump.tui.dump_formatting`), so the `write_block_text` wrapper always dispatches through the current module object. Block rendering picks up changes on reload without restarting.
