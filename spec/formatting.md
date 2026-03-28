# Formatting: The FormattedBlock IR

**Status:** draft

## Overview

### Why This Layer Exists

Claude Code sends complex API payloads containing system prompts, tool definitions, message histories with nested tool use/result pairs, streaming deltas, and metadata. A user looking at raw JSON would drown in structure. The formatting layer exists to parse this JSON into a typed intermediate representation (IR) that captures *what* the data means without deciding *how* it looks on screen.

This separation serves three purposes:

1. **Progressive disclosure is possible.** The IR carries enough structure that the rendering layer can show a one-line summary or full detail for the same block, without re-parsing API JSON.
2. **Hot-reload independence.** Formatting and rendering can be reloaded independently. Change how a tool block looks? Reload rendering. Change what fields are extracted from the API? Reload formatting. Neither disturbs the other.
3. **Testability without a TUI.** The IR is plain dataclasses. You can test formatting logic by asserting on field values, with no Textual dependency.

### The Two Entry Points

The formatting layer has two main entry points, corresponding to the two halves of an API exchange:

- **`format_request_for_provider()`** -- Parses a complete API request body into a hierarchical tree of blocks. This is the big one: it produces the system section, tool definitions, all conversation messages, metadata, and budget estimates.
- **`format_response_event()` / `format_complete_response_for_provider()`** -- Parses streaming SSE events or complete response messages into blocks. Simpler, because responses have less structure.

Both entry points return `list[FormattedBlock]`.

---

## The FormattedBlock Base Class

Every block in the IR inherits from `FormattedBlock`. The base class carries fields that are universal across all block types.

```
FormattedBlock
    block_id: int              # Unique, monotonically increasing. Auto-assigned.
    category: Category | None  # Context-dependent category override. None = use static mapping.
    show_during_streaming: bool # Whether this block renders during streaming. Default: False.
    content_regions: list[ContentRegion]  # Sub-regions for independent expand/collapse. Default: [].
    metadata: dict[str, str]   # Key-value metadata set at construction (e.g., cache zone). Default: {}.
    content: str               # Generic text payload. Default: "".
    session_id: str            # Claude Code session ID, stamped on all blocks. Default: "".
    _segment_result: SegmentResult | None  # Lazy cache for text segmentation. Default: None.
```

### Block Identity

`block_id` is allocated by a global monotonic counter (`FormatRuntime.next_block_id`). It serves as a stable key for view state (expansion overrides, strip caches) in the rendering layer. Block IDs are never reused within a process. The counter can be reset for tests via `reset_format_runtime_for_tests()`.

### Category

The `Category` enum has six values:

| Value | Meaning |
|-------|---------|
| `USER` | User message content |
| `ASSISTANT` | Assistant message content |
| `TOOLS` | Tool definitions, tool use, tool results |
| `SYSTEM` | System prompt sections |
| `METADATA` | HTTP headers, turn budgets, stream info, stop reasons, usage, session separators |
| `THINKING` | Extended thinking blocks |

A block's category determines which visibility filter controls it. The `category` field on the block is a context-dependent override -- for example, a `TextContentBlock` inside a user message gets `Category.USER`, while the same type inside a system section gets `Category.SYSTEM`. When `category` is `None`, the rendering layer falls back to a static mapping keyed by block type.

### Content Regions

Blocks with large text content (system prompts, user messages) are segmented into independently expandable/collapsible regions. System prompts can be 50+ screens long with dozens of XML sections; without per-region collapse, users must expand all or nothing. Each `ContentRegion` represents one structural segment:

```
ContentRegion
    index: int          # Position in parent's content_regions list
    kind: str           # "xml_block", "md", "code_fence", "md_fence", "tool_def"
    tags: list[str]     # Semantic labels for navigation (e.g., XML tag name, language). Default: [].
```

Regions are populated eagerly by `populate_content_regions()` after block construction. The function runs the segmentation parser (`segmentation.segment()`) on the block's `content` field and creates one `ContentRegion` per `SubBlock`. Tags are derived from:

- **XML blocks:** The tag name (e.g., `"system-reminder"`, `"env"`)
- **Code fences:** The info string / language (e.g., `"python"`, `"bash"`)
- **Content-derived patterns:** Text matching for `claude.md`, skill considerations, or tool use lists

Tags from structural metadata and content-derived patterns are merged, preserving order and deduplicating.

---

## Block Type Catalog

### Structural / Layout Blocks

#### `NewlineBlock`
An explicit blank line separator between messages.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| *(base only)* | | | No additional fields |

**Produced by:** `format_request()` between messages and at the end of the block list.

#### `SeparatorBlock`
A visual separator line.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `style` | `str` | `"heavy"` | `"heavy"` for request boundaries, `"thin"` between sections |

**Produced by:** `format_request()` around headers and between tool defs / system / messages sections.

### Header Blocks

#### `HeaderBlock`
Section header identifying a request or response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `label` | `str` | `""` | Display text, e.g. `"REQUEST #3"` or `"RESPONSE"` |
| `request_num` | `int` | `0` | Sequence number (1-based for requests, 0 for responses) |
| `timestamp` | `str` | `""` | Formatted as `"%-I:%M:%S %p"` (e.g., `"2:15:03 PM"`) |
| `header_type` | `str` | `"request"` | `"request"` or `"response"` |

**Produced by:** `format_request()` at the top of each request; `format_response_headers()` for responses.

#### `NewSessionBlock`
Indicates a new Claude Code session started (session ID changed between requests).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `session_id` | `str` | `""` | The new session UUID |

**Produced by:** `format_request()` when the session ID extracted from `metadata.user_id` differs from `state.current_session`. Emitted *before* the state is updated (the state mutation happens in `format_request_for_provider()` *after* formatting completes).

### Metadata Blocks

#### `MetadataBlock`
Key-value metadata from the request body.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `model` | `str` | `""` | Model name (e.g., `"claude-sonnet-4-20250514"`) |
| `max_tokens` | `str` | `""` | Max tokens setting, as string |
| `stream` | `bool` | `False` | Whether request uses streaming |
| `tool_count` | `int` | `0` | Number of tools defined |
| `user_hash` | `str` | `""` | User hash from `metadata.user_id` |
| `account_id` | `str` | `""` | Account UUID from `metadata.user_id` |

**Produced by:** `format_request()`, always. One per request, inside `MetadataSection`.

The `metadata.user_id` field is parsed using the pattern `user_<hash>_account_<uuid>_session_<uuid>`.

#### `HttpHeadersBlock`
HTTP request or response headers.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `headers` | `dict` | `{}` | Header name-value pairs |
| `header_type` | `str` | `"request"` | `"request"` or `"response"` |
| `status_code` | `int` | `0` | HTTP status code (response only) |

**Produced by:** `format_request_headers()` for requests, `format_response_headers()` for responses. Always produced, even when headers dict is empty.

#### `TurnBudgetBlock`
Per-turn token budget breakdown showing estimated context window usage.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `budget` | `TurnBudget` | `TurnBudget()` | See TurnBudget fields below |
| `tool_result_by_name` | `dict` | `{}` | `{tool_name: estimated_tokens}` for tool results |

The `TurnBudget` dataclass carries:

```
TurnBudget
    system_tokens_est: int          # Estimated system prompt tokens
    tool_defs_tokens_est: int       # Estimated tool definition tokens
    user_text_tokens_est: int       # Estimated user text tokens
    assistant_text_tokens_est: int  # Estimated assistant text tokens
    tool_use_tokens_est: int        # Estimated tool use input tokens
    tool_result_tokens_est: int     # Estimated tool result tokens
    total_est: int                  # Sum of all estimates
    actual_input_tokens: int        # Actual fresh input tokens (from API)
    actual_cache_read_tokens: int   # Actual cache-read tokens (from API)
    actual_cache_creation_tokens: int # Actual cache-creation tokens (from API)
    actual_output_tokens: int       # Actual output tokens (from API)
```

**Produced by:** `format_request()`, always. One per request, inside `MetadataSection`. The `tool_result_by_name` breakdown is computed by correlating tool results with their tool names (see Tool Correlation below).

### Container Blocks (Hierarchical)

Container blocks have a `children: list[FormattedBlock]` field. The rendering pipeline flattens them for display.

#### `MetadataSection`
Groups request metadata: `MetadataBlock` + `HttpHeadersBlock` + `TurnBudgetBlock`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `children` | `list[FormattedBlock]` | `[]` | Always 3 children in practice |

**Category:** `METADATA`

#### `SystemSection`
Groups the system prompt content from `body.system`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `children` | `list[FormattedBlock]` | `[]` | `TextContentBlock` instances, one per system block |

**Category:** `SYSTEM`. The `metadata` dict may contain `{"cache": "cached"|"cache write"|"fresh"}` when cache zone analysis is available.

**Produced by:** `format_request()`, always (even when system is empty -- renderer handles empty children).

#### `ToolDefsSection`
Groups tool definitions from `body.tools`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `tool_count` | `int` | `0` | Number of tools |
| `total_tokens` | `int` | `0` | Estimated total tokens for all tool definitions |
| `children` | `list[FormattedBlock]` | `[]` | `ToolDefBlock` instances |

**Category:** `TOOLS`. May carry cache zone in `metadata`.

**Produced by:** `format_request()`, always.

#### `ToolDefBlock`
Individual tool definition (child of `ToolDefsSection`).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Tool name (e.g., `"Read"`, `"Bash"`, `"Skill"`) |
| `description` | `str` | `""` | Tool description text |
| `input_schema` | `dict` | `{}` | JSON Schema for tool input |
| `token_estimate` | `int` | `0` | Estimated tokens for this tool definition |
| `children` | `list[FormattedBlock]` | `[]` | For compound tools: `SkillDefChild` or `AgentDefChild` |

**Category:** `TOOLS`

**Compound tool parsing:** Two tools receive special treatment:

- **`Skill`** -- Description is parsed for `- name: description` lines, producing `SkillDefChild` blocks. Plugin source is extracted from the `namespace:name` format.
- **`Task`** -- Description is parsed similarly, producing `AgentDefChild` blocks. `(Tools: ...)` suffixes are extracted into `available_tools`.

#### `SkillDefChild`
Individual skill within the Skill tool definition.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Skill name (e.g., `"commit"`, `"ms-office-suite:pdf"`) |
| `description` | `str` | `""` | Skill description |
| `plugin_source` | `str` | `""` | Plugin namespace (e.g., `"ms-office-suite"`) |

**Category:** `TOOLS`

#### `AgentDefChild`
Individual agent type within the Task tool definition.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Agent name |
| `description` | `str` | `""` | Agent description |
| `available_tools` | `str` | `""` | Comma-separated tool list (e.g., `"All tools"`) |

**Category:** `TOOLS`

#### `MessageBlock`
Container for one entry in the `messages[]` array.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `role` | `str` | `""` | `"user"` or `"assistant"` |
| `msg_index` | `int` | `0` | Index in the messages array |
| `timestamp` | `str` | `""` | Formatted timestamp |
| `children` | `list[FormattedBlock]` | `[]` | Content blocks (text, tool use, tool result, etc.) |

**Category:** Set from role: `USER`, `ASSISTANT`, or `SYSTEM`. May carry cache zone in `metadata`.

**Produced by:** `format_request()`, one per message. Also produced by `format_complete_response()` wrapping response content.

#### `ResponseMetadataSection`
Container for response HTTP headers and model info.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `children` | `list[FormattedBlock]` | `[]` | `HeaderBlock` (RESPONSE) + `HttpHeadersBlock` |

**Category:** `METADATA`

**Produced by:** `format_response_headers()`.

### Content Blocks

#### `TextContentBlock`
Plain text content from a message.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The text |
| `indent` | `str` | `"    "` | Indentation prefix for rendering |

**Category:** Inherited from parent message role (`USER`, `ASSISTANT`, `SYSTEM`).

**Produced by:** `format_request()` for message text content, system prompt sections. User-role text undergoes decomposition (see User Text Decomposition below).

#### `ConfigContentBlock`
Injected configuration content detected within a user message (CLAUDE.md files, plugin content, agent instructions).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The configuration text |
| `source` | `str` | `""` | Origin identifier (e.g., `"project CLAUDE.md"`, tag name) |
| `indent` | `str` | `"    "` | Indentation prefix |

**Category:** Inherited from parent role.

**Produced by:** User text decomposition when XML tags or `"Contents of ... CLAUDE.md"` patterns are detected.

#### `HookOutputBlock`
Hook output injected into user messages.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The inner content of the hook tag |
| `hook_name` | `str` | `""` | `"system-reminder"` or `"user-prompt-submit-hook"` |
| `indent` | `str` | `"    "` | Indentation prefix |

**Category:** Inherited from parent role.

**Produced by:** User text decomposition when `<system-reminder>` or `<user-prompt-submit-hook>` XML tags are found.

#### `ThinkingBlock`
Extended thinking content from the API response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The thinking text |
| `indent` | `str` | `"    "` | Indentation prefix |

**Category:** `THINKING`

**Produced by:** Content block formatting when `type == "thinking"`.

#### `ImageBlock`
An image content block.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `media_type` | `str` | `""` | MIME type (e.g., `"image/png"`) |

**Category:** Inherited from parent role.

#### `UnknownTypeBlock`
An unrecognized content block type.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `block_type` | `str` | `""` | The unknown type string |

### Tool Blocks

#### `ToolUseBlock`
A `tool_use` content block from a message.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Tool name (e.g., `"Read"`, `"Bash"`) |
| `input_size` | `int` | `0` | Line count of string input values |
| `msg_color_idx` | `int` | `0` | Color index for correlation (mod 6 cycle) |
| `detail` | `str` | `""` | Tool-specific enrichment (file path, command preview) |
| `tool_use_id` | `str` | `""` | ID for correlating with tool results |
| `tool_input` | `dict` | `{}` | Raw input dict |
| `description` | `str` | `""` | Tool description from definitions (populated via state) |

**Produced by:** `_format_tool_use_content()` for Anthropic format, inline in `format_openai_request()` for OpenAI format.

**Tool detail extraction** uses a dispatch table keyed by tool name:

| Tool | Detail Extracted |
|------|-----------------|
| `Read`, `Write`, `Edit` | File path (front-ellipsed to 40 chars) |
| `Grep`, `Glob` | Search pattern (truncated to 60 chars) |
| `Bash` | First line of command (truncated to 60 chars) |
| `Skill` | Skill name |
| `mcp__plugin_repomix-mcp_repomix__file_system_read_file` | File path (`file_path`) |
| Other | Empty string |

#### `ToolResultBlock`
A `tool_result` content block from a message.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `size` | `int` | `0` | Line count of result text |
| `is_error` | `bool` | `False` | Whether the tool reported an error |
| `msg_color_idx` | `int` | `0` | Color index (from correlated ToolUseBlock) |
| `tool_use_id` | `str` | `""` | ID for correlation |
| `tool_name` | `str` | `""` | Tool name (from correlated ToolUseBlock) |
| `detail` | `str` | `""` | Copied from correlated ToolUseBlock |
| `content` | `str` | `""` | Actual result text |
| `tool_input` | `dict` | `{}` | From correlated ToolUseBlock |

**Produced by:** `_format_tool_result_content()`. Content is extracted from the API's `content` field, which may be a string or a list of `{type: "text", text: "..."}` parts.

#### `ToolUseSummaryBlock`
Summary of consecutive tool use/result pairs, produced by the rendering layer's `collapse_tool_runs()` pre-pass (not by formatting).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `tool_counts` | `dict` | `{}` | `{tool_name: count}` |
| `total` | `int` | `0` | Total tool invocations in the run |
| `first_block_index` | `int` | `0` | Index in original block list |

**Note:** This block is not produced by formatting -- it is synthesized by the rendering pipeline when tools visibility is at SUMMARY level or below.

### Streaming Blocks

These blocks are produced during response streaming and are later consolidated.

#### `StreamInfoBlock`
Model information from `message_start` or complete response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `model` | `str` | `""` | Model name |

#### `StreamToolUseBlock`
Tool use start during streaming.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Tool name |

#### `TextDeltaBlock`
A text delta from streaming response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The delta text |
| `show_during_streaming` | `bool` | `True` | Overrides base default |

**Category:** Set dynamically at construction time via the `category` field (typically `ASSISTANT`). The static `BLOCK_CATEGORY` mapping has no entry for `TextDeltaBlock` (maps to `None`), so the category must be set on the block instance.

**Produced by:** `format_response_event()` for `TextDeltaEvent` SSE events. Multiple deltas accumulate during streaming, then are consolidated into a single `TextContentBlock` at finalization.

#### `StopReasonBlock`
Stop reason from `message_delta`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `reason` | `str` | `""` | e.g., `"end_turn"`, `"tool_use"`, `"max_tokens"` |

#### `ResponseUsageBlock`
Actual token usage from the API response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `input_tokens` | `int` | `0` | Fresh input tokens |
| `output_tokens` | `int` | `0` | Output tokens generated |
| `cache_read_tokens` | `int` | `0` | Input tokens served from cache |
| `cache_creation_tokens` | `int` | `0` | Input tokens written to cache |
| `model` | `str` | `""` | Model name |

**Produced by:** `format_complete_response()`, always (renderer handles zeros).

### Error Blocks

#### `ErrorBlock`
HTTP error from the API.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `code` | `int` | `0` | HTTP status code |
| `reason` | `str` | `""` | Error message |

#### `ProxyErrorBlock`
Internal proxy error.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `error` | `str` | `""` | Error description |

---

## Request Formatting Pipeline

When `format_request_for_provider()` is called, the following happens:

### 1. State Mutation (Single Enforcer)

`format_request_for_provider()` is the sole mutator of `ProviderRuntimeState`:

```
ProviderRuntimeState
    request_counter: int             # Incremented before formatting
    current_session: str | None      # Updated after formatting (so format_request sees the old value)
    tool_descriptions: dict[str, str] # Updated before formatting (so ToolUseBlock.description is populated)
```

The ordering matters:
1. `request_counter` is incremented
2. `tool_descriptions` is extracted from the request body (before formatting, so ToolUseBlock can read it)
3. `format_request()` or `format_openai_request()` runs (reads state, does not mutate)
4. `current_session` is updated (after formatting, so NewSessionBlock emission sees the old value)

### 2. Provider Dispatch

The provider string determines which formatter runs:

| Provider Family | Request Formatter | Response Formatter |
|----------------|-------------------|-------------------|
| `anthropic` | `format_request()` | `format_complete_response()` |
| `openai` | `format_openai_request()` | `format_openai_complete_response()` |

Provider specs are looked up via `cc_dump.providers.get_provider_spec(provider)`.

### 3. Block Emission Order (Anthropic)

For an Anthropic request, blocks are emitted in this order:

```
NewlineBlock
SeparatorBlock(heavy)
HeaderBlock("REQUEST #N")
SeparatorBlock(heavy)
NewSessionBlock                         # only if session changed
MetadataSection
    MetadataBlock
    HttpHeadersBlock(request)
    TurnBudgetBlock
ToolDefsSection
    ToolDefBlock * N
SeparatorBlock(thin)
SystemSection
    TextContentBlock * N
SeparatorBlock(thin)
[for each message:]
    NewlineBlock                        # between messages (not before first)
    MessageBlock
        TextContentBlock | ConfigContentBlock | HookOutputBlock | ...
        ToolUseBlock * N
        ToolResultBlock * N
NewlineBlock
```

### 4. Post-Processing

After all blocks are created, `format_request()` walks the entire tree and:
- Calls `populate_content_regions()` on every block (idempotent)
- Stamps `session_id` on every block (including children)

### 5. Cache Zone Annotation

When `cache_zones` is provided (from `analysis.compute_cache_zones()`), the `metadata["cache"]` field is set on container blocks:
- `ToolDefsSection` gets `cache_zones["tools"]`
- `SystemSection` gets `cache_zones["system"]`
- `MessageBlock` at index `i` gets `cache_zones["message:{i}"]`

Cache zone values are `"cached"`, `"cache write"`, or `"fresh"` (from the `CacheZone` enum).

---

## User Text Decomposition

User messages undergo special parsing to identify injected configuration and hooks. This is critical because Claude Code injects CLAUDE.md files, system reminders, and hook outputs into user messages, and making these visible is a core cc-dump feature.

### Detection Pipeline

`_format_user_text_content()` runs the segmentation parser on the raw text, then classifies each segment:

1. **XML blocks with hook tags** (`<system-reminder>`, `<user-prompt-submit-hook>`) become `HookOutputBlock` with the inner content extracted.

2. **XML blocks with other tags** become `ConfigContentBlock` with the tag name as `source`.

3. **Non-XML segments** are passed to `_append_text_or_config_segments()`, which scans for `"Contents of ... CLAUDE.md"` or `"Contents of ... AGENTS.md"` patterns. Matched regions become `ConfigContentBlock`; unmatched text becomes `TextContentBlock`.

### Example

Given a user message containing:
```
<system-reminder>
Contents of /home/user/.claude/CLAUDE.md:
Always use TypeScript.
</system-reminder>
Here is my actual question.
```

The decomposition produces:
```
HookOutputBlock(hook_name="system-reminder", content="Contents of /home/user/.claude/CLAUDE.md:\nAlways use TypeScript.\n")
TextContentBlock(content="Here is my actual question.")
```

For non-XML structured text like:
```
Contents of /project/CLAUDE.md (project instructions):
Use pytest for testing.
Contents of /home/user/.claude/CLAUDE.md (user instructions):
Prefer functional style.
```

The decomposition produces:
```
ConfigContentBlock(source="/project/CLAUDE.md", content="Use pytest for testing.\n")
ConfigContentBlock(source="/home/user/.claude/CLAUDE.md", content="Prefer functional style.\n")
```

---

## System Prompt Handling

### Current Behavior

System prompts from `body.system` are converted to plain `TextContentBlock` instances inside a `SystemSection` container. The system field may be a string or a list of `{text: "...", type: "text"}` blocks. Each non-empty text block becomes one `TextContentBlock` with `category=SYSTEM`.

### Historical Note: Content Tracking

The ARCHITECTURE.md describes a content-hashing system where system prompt sections are tracked across requests with SHA256 hashes, color-coded tags (`[sp-1]`, `[sp-2]`), and unified diffs for changed content. This feature was implemented via `TrackedContentBlock` but has been removed from the current codebase. System prompts are now rendered as plain text without cross-request tracking or diffing. [UNVERIFIED: whether content tracking is planned for re-implementation or has been permanently removed]

---

## Tool Correlation

### Why It Exists

Claude Code makes heavy use of tools. A single request may contain dozens of tool_use/tool_result pairs from the conversation history. Without correlation, a user sees generic "tool result" blocks with no indication of which tool produced them. Tool correlation links each result back to its use, carrying the tool name, color, detail string, and input for display.

### Mechanism (Formatting Layer)

Tool correlation in formatting operates within a single request, using a per-request `tool_id_map`:

```python
tool_id_map: dict[str, tuple[str, int, str, dict]]
# tool_use_id -> (tool_name, color_index, detail_string, tool_input)
```

**Recording phase:** When a `tool_use` content block is formatted, its `tool_use_id` is recorded in the map along with its name, assigned color index, detail string, and raw input.

**Lookup phase:** When a `tool_result` content block is formatted, its `tool_use_id` is looked up in the map. If found, the result block inherits the tool's name, color index, detail string, and input dict. If not found (orphaned result), the block falls back to using the message-level color index.

### Color Assignment

Tool colors use a 6-color cycle (`MSG_COLOR_CYCLE = 6`). Each `tool_use` block gets the next color in sequence (modulo 6). The corresponding `tool_result` block gets the same color index, creating visual pairing.

### Mechanism (Analysis Layer)

A separate correlation exists in `analysis.py:correlate_tools()` for database storage and aggregate analysis. This operates on raw message dicts (not FormattedBlocks) and produces `ToolInvocation` dataclasses:

```
ToolInvocation
    tool_use_id: str
    name: str
    input_str: str      # Raw JSON string of input (for token counting)
    result_str: str      # Raw result text (for token counting)
    is_error: bool
```

`correlate_tools()` handles both Anthropic format (`tool_use`/`tool_result` content blocks) and OpenAI format (`assistant.tool_calls` + `role="tool"` messages). The `tool_result_breakdown()` function uses this to compute per-tool-name token estimates for the budget display.

---

## Text Segmentation

### Why It Exists

System prompts and user messages contain a mix of markdown text, fenced code blocks, and XML tags. Treating the entire text as one opaque blob makes it impossible to collapse XML sections independently or apply syntax highlighting to code fences. Segmentation identifies the structural regions so the rendering layer can handle each appropriately.

### The Segmentation Algorithm

`segmentation.segment()` performs a single linear scan with document-order precedence. At each position, whichever structure (XML open or fence open) starts earliest wins, and its span is opaque (content inside is not re-scanned).

The result is a `SegmentResult`:

```
SegmentResult
    sub_blocks: tuple[SubBlock, ...]
    errors: tuple[ParseError, ...]
```

Each `SubBlock` has a kind, span, and optional metadata:

```
SubBlock
    kind: SubBlockKind   # MD, MD_FENCE, CODE_FENCE, XML_BLOCK
    span: Span           # start, end (exclusive)
    meta: FenceMeta | XmlBlockMeta | None
```

### SubBlock Kinds

| Kind | Description | Metadata |
|------|------------|----------|
| `MD` | Plain markdown (gap-fill between structures) | None |
| `MD_FENCE` | Fenced block with no info string (rendered as markdown) | `FenceMeta` |
| `CODE_FENCE` | Fenced block with language info (syntax highlighted) | `FenceMeta` |
| `XML_BLOCK` | `<tag>...</tag>` block | `XmlBlockMeta` |

### FenceMeta

```
FenceMeta
    marker_char: str     # "`" or "~"
    marker_len: int      # 3 or more
    info: str | None     # None for md_fence, first token for code_fence
    inner_span: Span     # Content between opening and closing fence lines
```

### XmlBlockMeta

```
XmlBlockMeta
    tag_name: str
    start_tag_span: Span
    end_tag_span: Span
    inner_span: Span
```

### XML Parsing Forms

Three forms of XML blocks are recognized:

- **Form A:** `<tag>content after open tag\n...\n</tag>` (content starts on same line as open tag)
- **Form B:** `<tag>\ncontent\n</tag>` (tags on their own lines)
- **Form C:** `<tag>content</tag>` (single line)

Comments (`<!--`), processing instructions (`<?`), CDATA (`<!`), closing tags (`</`), and self-closing tags (`/>`) are excluded.

### Error Handling

Unclosed fences and unclosed XML tags produce `ParseError` entries but do not halt parsing:
- Unclosed fences extend to end of text
- Unclosed XML tags are skipped (the open tag line is advanced past)

### Tag Visibility Rewriting

Two utility functions handle XML tag visibility in markdown rendering:

- `wrap_tags_in_backticks(text)` -- Wraps bare `<tag>` occurrences in backticks so they render visibly in Rich's Markdown widget (otherwise they'd be treated as HTML and hidden).
- `wrap_tags_outside_fences(text)` -- Same, but skips content inside fenced code regions (fences are handled natively by the markdown renderer).

---

## Special Content Classification

### Why It Exists

Users need to navigate quickly to interesting parts of the conversation: where is the CLAUDE.md content? Where are the skill definitions? Where is the tool list? Special content classification scans blocks for recognizable patterns and attaches navigation markers.

### Markers

| Key | Label | Detected In |
|-----|-------|------------|
| `claude_md` | `"CLAUDE.md"` | `ConfigContentBlock` (source contains "claude.md"), `TextContentBlock` (user category, content mentions claude.md) |
| `hook` | `"hook"` | `HookOutputBlock` (always) |
| `skill_consideration` | `"skills"` | `HookOutputBlock` (content matches skill patterns), `TextContentBlock` (user, content matches) |
| `skill_send` | `"skill send"` | `ToolUseBlock` (name == "Skill") |
| `tool_use_list` | `"tools"` | `HookOutputBlock` (content matches tool list patterns), `TextContentBlock` (user, content matches), `ToolDefsSection` (tool_count > 0) |

### Classification Dispatch

`markers_for_block(block)` dispatches to classifiers by block class name:

| Block Type | Classifier |
|-----------|-----------|
| `ConfigContentBlock` | Checks source for "claude.md" |
| `HookOutputBlock` | Always `hook`; content scanned for skill/tool patterns |
| `TextContentBlock` | User-category blocks scanned for claude.md/skill/tool patterns |
| `ToolUseBlock` | Name == "Skill" yields `skill_send` |
| `ToolDefsSection` | tool_count > 0 yields `tool_use_list` |

### Display vs. Navigation Markers

`display_markers_for_block()` filters to a subset intended for inline badges: `claude_md`, `skill_consideration`, `skill_send`, `tool_use_list`. The `hook` marker is used for navigation but not displayed as a badge.

### Location Collection

`collect_special_locations(turns, marker_key)` walks all completed turns (skipping streaming turns), traverses block trees in pre-order, and collects `SpecialLocation` entries:

```
SpecialLocation
    marker: SpecialMarker   # key + label
    turn_index: int
    block_index: int
    block: object            # Reference to the actual block
```

---

## Response Formatting

### Streaming Responses

During streaming, `format_response_event()` dispatches on SSE event type:

| Event Type | Blocks Produced |
|-----------|----------------|
| `MessageStartEvent` | `StreamInfoBlock(model=...)` |
| `TextBlockStartEvent` | *(none)* |
| `ToolUseBlockStartEvent` | `StreamToolUseBlock(name=...)` |
| `TextDeltaEvent` | `TextDeltaBlock(content=...)` if non-empty |
| `InputJsonDeltaEvent` | *(none)* |
| `ContentBlockStopEvent` | *(none)* |
| `MessageDeltaEvent` | `StopReasonBlock(reason=...)` if stop_reason != NONE |
| `MessageStopEvent` | *(none)* |

`TextDeltaBlock` is the only block with `show_during_streaming=True` by default. Multiple deltas accumulate during streaming and are consolidated into a single `TextContentBlock` at finalization (handled by the widget layer, not the formatting layer).

### Complete Responses

`format_complete_response()` handles non-streaming (or replay) responses. It produces:

```
StreamInfoBlock(model=...)
MessageBlock(role="assistant")
    TextContentBlock * N
    StreamToolUseBlock * N
    ThinkingBlock * N
StopReasonBlock(reason=...)
ResponseUsageBlock(input_tokens=..., output_tokens=..., cache_read_tokens=..., cache_creation_tokens=...)
```

The `MessageBlock` container mirrors the request-side message structure.

### OpenAI Responses

`format_openai_complete_response()` follows the same pattern but parses from `choices[0].message` format. It does not produce `ResponseUsageBlock` (OpenAI usage format differs). [UNVERIFIED: whether OpenAI usage is handled elsewhere or simply not tracked]

---

## Visibility Model

The `VisState` named tuple is the canonical representation of a block's visibility:

```
VisState(visible: bool, full: bool, expanded: bool)
```

Three orthogonal axes:
- **visible** -- Whether the block is shown at all (filter on/off)
- **full** -- Summary level vs. full detail level
- **expanded** -- Collapsed vs. expanded within current level

Constants:
- `HIDDEN = VisState(visible=False, full=False, expanded=False)`
- `ALWAYS_VISIBLE = VisState(visible=True, full=True, expanded=True)`

Note: `VisState` is defined in the formatting module as the canonical visibility representation, but the actual visibility *resolution* (mapping categories and user settings to VisState values) happens in the rendering layer. The formatting layer defines the vocabulary; the rendering layer applies the rules.

---

## OpenAI Format Differences

The formatting layer handles both Anthropic and OpenAI API formats. Key differences:

| Aspect | Anthropic | OpenAI |
|--------|-----------|--------|
| System prompt | `body.system` (separate field) | `messages` with `role="system"` |
| Tool definitions | `body.tools[].{name, description, input_schema}` | `body.tools[].function.{name, description, parameters}` |
| Tool use | `content[].{type: "tool_use", id, name, input}` | `message.tool_calls[].{id, function: {name, arguments}}` |
| Tool result | `content[].{type: "tool_result", tool_use_id, content}` | `{role: "tool", tool_call_id, content}` |
| Tool input | Parsed dict | JSON string in `arguments`, parsed at formatting time |
| Header label | `"REQUEST #N"` | `"REQUEST #N (ProviderName)"` |
| Response content | `content[].{type, text/thinking/tool_use}` | `choices[].message.{content, tool_calls}` |

Despite these differences, both paths produce the same IR block types. The OpenAI formatter does not currently support tool correlation within messages (no `tool_id_map`), and does not produce `ResponseUsageBlock`. [UNVERIFIED: whether these are intentional omissions or planned additions]
