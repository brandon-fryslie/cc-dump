# Export

> Status: draft
> Last verified against: not yet

## Overview

When a user is deep in a cc-dump session watching Claude Code traffic, they often need to capture what they've seen for later analysis, sharing, or filing a bug report. The conversation data is transient -- it lives in the TUI's memory and will be gone when the process exits. Export solves this by dumping the entire conversation to a plain-text file that preserves the structural information (turns, block types, metadata) without requiring cc-dump to read it back.

Export produces a human-readable text file from the current conversation state. It writes to a temporary file and optionally opens it in the user's editor. There is currently one format (plain text) and one trigger (the command palette).

## Trigger

Export is invoked via the Textual command palette as "Dump conversation" (`action_dump_conversation`). There is no dedicated keybinding. The action is registered as a `SystemCommand` with the description "Export conversation to text file."

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
1. A header line showing the block index (zero-based within the turn) and the block type name
2. A separator line (76 dashes, indented 2 spaces)
3. Block-specific content, indented 2 spaces

Children of hierarchical blocks (e.g., children of `ToolDefsSection`) are rendered recursively with the same format, sharing the turn-level block counter.

### Block types and their text output

| Block Type | Fields Written |
|---|---|
| `HeaderBlock` | `label`, `timestamp` (if present) |
| `HttpHeadersBlock` | `header_type` (uppercased), `status_code` (if present), all `headers` as key-value pairs |
| `MetadataBlock` | `model`, `max_tokens`, `stream`, `tool_count` (each if present) |
| `TextContentBlock` | `content` |
| `ToolUseBlock` | `name`, `tool_use_id`, `detail` (if present), `input_size` (if present) |
| `ToolResultBlock` | `tool_name`, `tool_use_id`, `detail` (if present), error status with `size`, or `size` as result lines |
| `ToolUseSummaryBlock` | Per-tool counts, total |
| `ImageBlock` | `media_type` |
| `UnknownTypeBlock` | `block_type` |
| `StreamInfoBlock` | `model` |
| `StreamToolUseBlock` | `name` |
| `TextDeltaBlock` | `content` |
| `StopReasonBlock` | `reason` |
| `ResponseUsageBlock` | Total input tokens (input + cache_read + cache_creation) and output tokens, with cache breakdown if cache tokens > 0 |
| `ErrorBlock` | `code`, `reason` (if present) |
| `ProxyErrorBlock` | `error` |
| `TurnBudgetBlock` | `total_est`, `actual_input_tokens`, `actual_output_tokens`, `actual_cache_creation_tokens`, `actual_cache_read_tokens` (each if present, formatted via `fmt_tokens`) |
| `MetadataSection` | Label "METADATA" |
| `ToolDefsSection` | Label "TOOL DEFINITIONS (N tools)" with child count |
| `SystemSection` | Label "SYSTEM" |
| `MessageBlock` | `role` (uppercased) with `msg_index`, `timestamp` (if present) |
| `ResponseMetadataSection` | Label "RESPONSE METADATA" |
| `ToolDefBlock` | `name`, `token_count` (if present, formatted via `fmt_tokens`) |
| `SkillDefChild` | `name` |
| `AgentDefChild` | `name` |
| `SeparatorBlock` | Label "(separator: <style>)" |
| `NewlineBlock` | Label "(newline)" |

Unhandled block types produce `(unhandled block type: <TypeName>)` and log a warning.

## File Output

- **Location:** System temp directory via `tempfile.mkstemp`, with prefix `cc-dump-` and suffix `.txt`
- **Notification:** The file path is shown via Textual's `notify()` and logged at INFO level

## Editor Integration

On macOS (`platform.system() == "Darwin"`), if the `$VISUAL` environment variable is set, cc-dump attempts to open the exported file in that editor:

- The editor command is invoked as `[$VISUAL, <path>]` via `subprocess.run`
- **Timeout:** 20 seconds. If the editor hasn't exited by then, cc-dump logs a warning ("still running in background") and continues. This timeout accommodates GUI editors like `open` or `code` that return quickly, while not blocking indefinitely on terminal editors.
- **Failure handling:** Non-zero exit codes are logged as warnings. Exceptions are logged as errors and shown via `notify()` with error severity.

On non-macOS platforms, or when `$VISUAL` is not set, the file is created but no editor is opened. The user must navigate to the temp path manually.

## Edge Cases

- **Empty conversation:** If no turns exist, export shows a warning notification ("No conversation to dump") and does not create a file.
- **Write failure:** Any exception during file creation or writing is caught, logged as ERROR, and shown via `notify()` with error severity.
- **File cleanup:** Temp files are not automatically cleaned up. They persist until the OS cleans the temp directory or the user deletes them. [UNVERIFIED: whether OS temp cleanup policy is documented anywhere]

## What Is Not Exported

- Visibility state (which blocks are expanded/collapsed)
- Rendering styles or colors
- Scroll position or follow-mode state
- Search highlights
- Error indicator overlay state
- HAR recording data (that is a separate system; see `spec/recording.md`)

## Hot Reload

Both `dump_export` and `dump_formatting` are hot-reloadable modules. The `dump_export` module delegates to `dump_formatting` via module-level import (`import cc_dump.tui.dump_formatting`), so block rendering picks up changes on reload without restarting.
