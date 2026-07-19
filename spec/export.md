# Export

## Overview

When a user is deep in a cc-dump session watching Claude Code traffic, they often need to capture what they've seen for later analysis, sharing, or filing a bug report. The conversation data is transient -- it lives in the TUI's memory and will be gone when the process exits. Export solves this by dumping the entire conversation to a plain-text file that preserves the structural information (turns, block types, metadata) without requiring cc-dump to read it back.

Export produces a human-readable text file from the current conversation state. It writes to a temporary file and optionally opens it in the user's editor. There is one format (plain text) and one trigger (the command palette).

## Trigger

Export is invoked via the Textual command palette as a `SystemCommand` with the title "Dump conversation" and description "Export conversation to text file". The action method is `action_dump_conversation` on the app. There is no dedicated keybinding -- users open the command palette (ctrl+p) and search for "dump".

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
  ----------------------------------------------------------------------------
  Request #1 → POST /v1/messages
  Timestamp: 2026-03-28T10:00:00Z

  [1] MetadataBlock
  ----------------------------------------------------------------------------
  Model: claude-sonnet-4-20250514
  Max tokens: 16384
  Stream: True
  Tool count: 42

  ...
```

The top-level header is 80 `=` characters, then the title, then 80 `=` characters. Each turn is preceded by 80 `─` (box-drawing horizontal) characters, a 1-indexed turn number, then 80 `─` characters again. All separators are 80 characters wide.

### Block rendering

Each block is rendered with:
1. A header line showing the block index (zero-based within the turn) and the block type name (Python class name), indented 2 spaces
2. A separator line of 76 `-` (ASCII hyphen) characters, indented 2 spaces (total width: 78)
3. Block-specific content, indented 2 spaces

Children of hierarchical blocks (e.g., children of `ToolDefsSection`) are rendered recursively with the same format, sharing a turn-level block counter (a mutable `[0]` list incremented after each block). The counter increments after each block's content is written but before its children are processed, so children get consecutive indices following their parent.

### Block types and their text output

| Block Type | Fields Written |
|---|---|
| `HeaderBlock` | `label`, `timestamp` (if truthy) |
| `HttpHeadersBlock` | `header_type` (uppercased, suffixed with " Headers"), `status_code` (if truthy, labeled "Status"), all `headers` dict entries as key-value pairs |
| `MetadataBlock` | `model` (if truthy), `max_tokens` (if truthy), `stream` (always written), `tool_count` (if truthy) |
| `TextContentBlock` | `content` (if truthy) |
| `ToolUseBlock` | `name` (labeled "Tool"), `tool_use_id` (labeled "ID"), `detail` (if truthy, labeled "Detail"), `input_size` (if truthy, labeled "Input lines") |
| `ToolResultBlock` | `tool_name` (labeled "Tool"), `tool_use_id` (labeled "ID"), `detail` (if truthy, labeled "Detail"); if `is_error`: "ERROR ({size} lines)", otherwise: "Result lines: {size}" (size always written in non-error case) |
| `ToolUseSummaryBlock` | "Tool counts:" header, per-tool name:count pairs (indented 4 spaces), `total` (labeled "Total") |
| `ImageBlock` | `media_type` (labeled "Media type") |
| `UnknownTypeBlock` | `block_type` (labeled "Unknown block type") |
| `StreamInfoBlock` | `model` (labeled "Model") |
| `StreamToolUseBlock` | `name` (labeled "Tool") |
| `TextDeltaBlock` | `content` (if truthy) |
| `StopReasonBlock` | `reason` (labeled "Stop reason") |
| `ResponseUsageBlock` | Total input tokens (input + cache_read + cache_creation) and output tokens formatted as "Usage: N in → N out". If either cache_read or cache_creation tokens > 0, appends a parenthetical: always includes "cache_read: N", and adds ", cache_creation: N" only if cache_creation > 0 |
| `ErrorBlock` | `code` (labeled "Error"), `reason` (if truthy, labeled "Reason") |
| `ProxyErrorBlock` | `error` (labeled "Error") |
| `TurnBudgetBlock` | Reads from `block.budget` sub-object: `total_est`, `actual_input_tokens`, `actual_output_tokens`, `actual_cache_creation_tokens`, `actual_cache_read_tokens` (each if truthy, formatted via `fmt_tokens`) |
| `MetadataSection` | Label "METADATA" |
| `ToolDefsSection` | Label "TOOL DEFINITIONS (N tools)" where N is `len(block.children)` |
| `SystemSection` | Label "SYSTEM" |
| `MessageBlock` | `role` (uppercased) with `msg_index` in brackets, `timestamp` (if truthy) |
| `ResponseMetadataSection` | Label "RESPONSE METADATA" |
| `ToolDefBlock` | `name` (labeled "Tool"), `token_count` (if truthy, formatted via `fmt_tokens`, labeled "Tokens") |
| `SkillDefChild` | `name` (labeled "Skill") |
| `AgentDefChild` | `name` (labeled "Agent") |
| `SeparatorBlock` | Label "(separator: {style})" |
| `NewlineBlock` | Label "(newline)" |

The following `FormattedBlock` subclasses have **no entry** in `BLOCK_WRITERS` and produce the unhandled fallback:

| Block Type | Notes |
|---|---|
| `NewSessionBlock` | Session boundary marker |
| `ThinkingBlock` | Extended thinking content |
| `ConfigContentBlock` | CLAUDE.md / config content |
| `HookOutputBlock` | Hook output content |

Unhandled block types produce `(unhandled block type: <TypeName>)` and log a warning via the optional `log_fn` callback.

### Dispatch mechanism

Block type dispatch is data-driven via the `BLOCK_WRITERS` dictionary in `dump_formatting.py`, keyed by block type class. Each value is a callable `(TextIO, block) -> None`. The `write_block_text` function writes the header (index + type name + separator), then looks up and calls the handler, falling back to the unhandled-type message.

### Programmatic access

`format_conversation_text(conv, log_fn=None) -> str` builds the complete dump text in memory via `io.StringIO` and returns it as a string. This is what `dump_conversation` calls internally, but it is available for use outside the TUI context (e.g., testing).

## File Output

- **Location:** System temp directory via `tempfile.mkstemp`, with prefix `cc-dump-` and suffix `.txt`
- **Encoding:** Written via `os.fdopen(fd, "w")` using the system default encoding
- **Notification:** The file path is shown via Textual's `notify()` (default severity) and logged at INFO level

## Editor Integration

After writing the file, cc-dump checks two conditions: `platform.system() == "Darwin"` and the `$VISUAL` environment variable is set. If both are true, it opens the exported file in that editor.

This is a **deliberate scope choice**, not a technical limitation. There is no platform-specific API usage -- the check is a single `platform.system()` string comparison. macOS is the primary development platform for cc-dump, and `$VISUAL` is the standard Unix convention for the user's preferred visual editor. Extending to Linux would be a one-line change to the platform guard. The guard exists because the behavior has only been tested on macOS.

### Editor invocation details

- The editor command is invoked as `[$VISUAL, <path>]` via `subprocess.run` with `capture_output=True` and `text=True`
- A second `notify()` call informs the user the editor is being opened, showing the editor name
- **Timeout:** 20 seconds. If the editor process hasn't exited by then, `subprocess.TimeoutExpired` is caught, cc-dump logs a warning ("Editor timeout after 20s (still running in background)") and shows a warning notification ("Editor timeout (still open)"). This timeout accommodates GUI editors like `open` or `code` that return quickly, while not blocking indefinitely on terminal editors that would take over the TUI's terminal.
- **Success:** Exit code 0 is logged at INFO level ("Editor opened successfully"). No user-facing notification beyond the initial "Opening in..." one.
- **Failure:** Non-zero exit codes are logged as warnings (no user notification). Exceptions during `subprocess.run` are logged as errors and shown via `notify()` with error severity.

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
