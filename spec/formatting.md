# Formatting: The FormattedBlock IR

**Status:** draft-3

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

### Module Structure

The public API surface is `cc_dump.core.formatting`, a thin facade that delegates entirely to `cc_dump.core.formatting_impl` via `__getattr__`. All types, functions, and state live in `formatting_impl`. Supporting modules:

- **`segmentation.py`** -- Text segmentation parser (markdown, fences, XML)
- **`special_content.py`** -- Navigation marker classification
- **`coerce.py`** -- Scalar/map coercion helpers (`coerce_int`, `coerce_optional_int`, `coerce_str_object_dict`)
- **`analysis.py`** -- `TurnBudget`, `compute_turn_budget`, `estimate_tokens`, `tool_result_breakdown`, `correlate_tools`

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

Large text blocks (system prompts, user messages, hook outputs) can contain dozens of XML sections, code fences, and markdown regions. Without per-region collapse, users must expand all or nothing -- a serious problem when a single system prompt fills 50+ screens. Content regions solve this by identifying independently expandable/collapsible structural segments within a block.

Each `ContentRegion` represents one segment identified by the segmentation parser:

```
ContentRegion
    index: int          # Position in parent's content_regions list
    kind: str           # "xml_block", "md", "code_fence", "md_fence", "tool_def"
    tags: list[str]     # Semantic labels for navigation (e.g., XML tag name, language). Default: [].
```

Regions are populated eagerly by `populate_content_regions()` after block construction. The function runs the segmentation parser (`segmentation.segment()`) on the block's `content` field and creates one `ContentRegion` per `SubBlock`. Tags are derived from two sources, merged with deduplication:

1. **Structural metadata:**
   - XML blocks: the tag name (e.g., `"system-reminder"`, `"env"`)
   - Code fences: the info string / language (e.g., `"python"`, `"bash"`)
2. **Content-derived patterns** (scanned via `_derived_region_tags()`):
   - `claude.md` (case-insensitive word boundary match)
   - Skill consideration patterns (e.g., "following skills are available")
   - Tool use list patterns (e.g., "following tools are available")

`populate_content_regions()` is idempotent -- it returns immediately if `content_regions` is already populated. It is called only in the Anthropic request path (`format_request`), not in the OpenAI request path.

---

## Block Type Catalog

### Structural / Layout Blocks

#### `NewlineBlock`
An explicit blank line separator between messages.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| *(base only)* | | | No additional fields |

**Produced by:** `format_request()` and `format_openai_request()` between messages and at the end of the block list, and as the first block in the list.

#### `SeparatorBlock`
A visual separator line.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `style` | `str` | `"heavy"` | `"heavy"` for request boundaries, `"thin"` between sections |

**Produced by:** `format_request()` and `format_openai_request()` around headers and between tool defs / system / messages sections.

### Header Blocks

#### `HeaderBlock`
Section header identifying a request or response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `label` | `str` | `""` | Display text, e.g. `"REQUEST #3"` or `"RESPONSE"` |
| `request_num` | `int` | `0` | Sequence number (1-based for requests, 0 for responses) |
| `timestamp` | `str` | `""` | Formatted as `"%-I:%M:%S %p"` (e.g., `"2:15:03 PM"`) |
| `header_type` | `str` | `"request"` | `"request"` or `"response"` |

**Produced by:** `format_request()` at the top of each request. For responses, `format_response_headers()` produces a `ResponseMetadataSection` whose children include a `HeaderBlock` (with `header_type="response"`) -- `HeaderBlock` is not a direct top-level output of that function. For OpenAI providers, the label includes the provider name: `"REQUEST #3 (OpenRouter)"`.

#### `NewSessionBlock`
Indicates a new Claude Code session started (session ID changed between requests).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `session_id` | `str` | `""` | The new session UUID |

**Produced by:** `format_request()` when the session ID extracted from `metadata.user_id` differs from `state.current_session`. Emitted *before* the state is updated (the state mutation happens in `format_request_for_provider()` *after* formatting completes). Only produced in the Anthropic path -- OpenAI requests do not carry `metadata.user_id`.

### Metadata Blocks

#### `MetadataBlock`
Key-value metadata from the request body.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `model` | `str` | `""` | Model name (e.g., `"claude-sonnet-4-20250514"`) |
| `max_tokens` | `str` | `""` | Max tokens setting, as string |
| `stream` | `bool` | `False` | Whether request uses streaming |
| `tool_count` | `int` | `0` | Number of tools defined |
| `user_hash` | `str` | `""` | User hash from `metadata.user_id` (Anthropic only) |
| `account_id` | `str` | `""` | Account UUID from `metadata.user_id` (Anthropic only) |

**Produced by:** `format_request()` and `format_openai_request()`, always. One per request, inside `MetadataSection`. The OpenAI path does not populate `user_hash` or `account_id` (these remain empty strings).

The `metadata.user_id` field is parsed using the pattern `user_<hash>_account_<uuid>_session_<uuid>` via `parse_user_id()`.

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

The `TurnBudget` dataclass (from `analysis.py`) carries:

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

`TurnBudget` also has a `cache_hit_ratio` property: `actual_cache_read_tokens / (actual_input_tokens + actual_cache_read_tokens)`.

**Produced by:** `format_request()` and `format_openai_request()`, always. One per request, inside `MetadataSection`. The `tool_result_by_name` breakdown is computed by `tool_result_breakdown()`, which correlates tool results with their tool names (see Tool Correlation below).

### Container Blocks (Hierarchical)

Container blocks have a `children: list[FormattedBlock]` field. The rendering pipeline flattens them for display.

#### `MetadataSection`
Groups request metadata: `MetadataBlock` + `HttpHeadersBlock` + `TurnBudgetBlock`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `children` | `list[FormattedBlock]` | `[]` | Always 3 children in practice |

**Category:** `METADATA`

#### `SystemSection`
Groups the system prompt content from `body.system` (Anthropic) or `role="system"` messages (OpenAI).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `children` | `list[FormattedBlock]` | `[]` | `TextContentBlock` instances, one per system block |

**Category:** `SYSTEM`. The `metadata` dict may contain `{"cache": "cached"|"cache write"|"fresh"}` when cache zone analysis is available (Anthropic path only).

**Produced by:** `format_request()`, always (even when system is empty -- renderer handles empty children). In the OpenAI path, system messages are extracted from the messages array and placed here; they are skipped during the conversation message loop.

#### `ToolDefsSection`
Groups tool definitions from `body.tools`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `tool_count` | `int` | `0` | Number of tools |
| `total_tokens` | `int` | `0` | Estimated total tokens for all tool definitions |
| `children` | `list[FormattedBlock]` | `[]` | `ToolDefBlock` instances |

**Category:** `TOOLS`. May carry cache zone in `metadata` (Anthropic path only).

**Produced by:** `format_request()` and `format_openai_request()`, always.

#### `ToolDefBlock`
Individual tool definition (child of `ToolDefsSection`).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Tool name (e.g., `"Read"`, `"Bash"`, `"Skill"`) |
| `description` | `str` | `""` | Tool description text |
| `input_schema` | `dict` | `{}` | JSON Schema for tool input (Anthropic: `input_schema`, OpenAI: `parameters`) |
| `token_estimate` | `int` | `0` | Estimated tokens for this tool definition |
| `children` | `list[FormattedBlock]` | `[]` | For compound tools: `SkillDefChild` or `AgentDefChild` |

**Category:** `TOOLS`

**Compound tool parsing:** Two tools receive special treatment in the Anthropic path (the OpenAI path does not parse compound tools):

- **`Skill`** -- Description is parsed for `- name: description` lines via `_parse_named_definition_children()`, producing `SkillDefChild` blocks. Plugin source is extracted from the `namespace:name` format (e.g., `"ms-office-suite:pdf"` yields `plugin_source="ms-office-suite"`).
- **`Task`** -- Description is parsed similarly, producing `AgentDefChild` blocks. `(Tools: ...)` suffixes are extracted into `available_tools`.

#### `SkillDefChild`
Individual skill within the Skill tool definition.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Skill name (e.g., `"commit"`, `"ms-office-suite:pdf"`) |
| `description` | `str` | `""` | Skill description (surrounding quotes stripped) |
| `plugin_source` | `str` | `""` | Plugin namespace (e.g., `"ms-office-suite"`), empty if no colon in name |

**Category:** `TOOLS`

#### `AgentDefChild`
Individual agent type within the Task tool definition.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Agent name |
| `description` | `str` | `""` | Agent description (quotes stripped, `(Tools: ...)` suffix removed) |
| `available_tools` | `str` | `""` | Tool list text (e.g., `"All tools"`), extracted from `(Tools: ...)` suffix |

**Category:** `TOOLS`

#### `MessageBlock`
Container for one entry in the `messages[]` array.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `role` | `str` | `""` | `"user"`, `"assistant"`, or `"tool"` (OpenAI) |
| `msg_index` | `int` | `0` | Index in the messages array |
| `timestamp` | `str` | `""` | Formatted timestamp |
| `children` | `list[FormattedBlock]` | `[]` | Content blocks (text, tool use, tool result, etc.) |

**Category:** Set from role: `USER`, `ASSISTANT`, `TOOLS` (OpenAI tool role), or `SYSTEM`. May carry cache zone in `metadata` (Anthropic path).

**Produced by:** `format_request()` and `format_openai_request()`, one per message. Also produced by `format_complete_response()` and `format_openai_complete_response()` wrapping response content.

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
| `indent` | `str` | `"    "` | Indentation prefix for rendering (4 spaces) |

**Category:** Inherited from parent message role (`USER`, `ASSISTANT`, `SYSTEM`).

**Produced by:** `format_request()` for message text content, system prompt sections. User-role text undergoes decomposition (see User Text Decomposition below). When a message's `content` field is a bare string (rather than a list of content blocks), the string is wrapped directly in a `TextContentBlock` without decomposition. When content blocks are strings (rather than dicts), they are truncated to 200 characters.

#### `ConfigContentBlock`
Injected configuration content detected within a user message (CLAUDE.md files, plugin content, agent instructions).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The configuration text (for XML blocks: the full `<tag>...</tag>` text; for regex matches: the text between matched headers) |
| `source` | `str` | `""` | Origin identifier: XML tag name for XML-detected blocks (e.g., `"context-specific"`), or file path for regex-detected blocks (e.g., `"/project/CLAUDE.md"`) |
| `indent` | `str` | `"    "` | Indentation prefix |

**Category:** Inherited from parent role.

**Produced by:** User text decomposition. Two detection paths:

1. **XML path:** Non-hook XML tags detected by segmentation. The `source` is set to the XML tag name, and `content` is the full XML text including tags.
2. **Regex path:** `"Contents of ... CLAUDE.md"` or `"Contents of ... AGENTS.md"` patterns detected by `_CONFIG_SOURCE_RE`. The `source` is the file path, and `content` is the text following the matched header up to the next header or end of text.

#### `HookOutputBlock`
Hook output injected into user messages.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The inner content of the hook tag (text between open and close tags, *not* including the tags) |
| `hook_name` | `str` | `""` | `"system-reminder"` or `"user-prompt-submit-hook"` |
| `indent` | `str` | `"    "` | Indentation prefix |

**Category:** Inherited from parent role.

**Produced by:** User text decomposition when `<system-reminder>` or `<user-prompt-submit-hook>` XML tags are found. These two tag names are listed in `_HOOK_XML_TAGS`.

#### `ThinkingBlock`
Extended thinking content from the API response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The thinking text |
| `indent` | `str` | `"    "` | Indentation prefix |

**Category:** `THINKING`

**Produced by:** Content block formatting when `type == "thinking"`. The thinking text is extracted from the `thinking` key (not `text`).

#### `ImageBlock`
An image content block.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `media_type` | `str` | `""` | MIME type from `source.media_type` (e.g., `"image/png"`) |

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
| `input_size` | `int` | `0` | Sum of `(line_count)` across all string-valued inputs, minimum 1 |
| `msg_color_idx` | `int` | `0` | Color index for correlation (mod 6 cycle) |
| `detail` | `str` | `""` | Tool-specific enrichment (file path, command preview) |
| `tool_use_id` | `str` | `""` | ID for correlating with tool results |
| `tool_input` | `dict` | `{}` | Raw input dict |
| `description` | `str` | `""` | Tool description from definitions (populated via `state.tool_descriptions`) |

**Produced by:** `_format_tool_use_content()` for Anthropic format. In OpenAI format, `ToolUseBlock` is created inline within `format_openai_request()` and `format_openai_complete_response()`, but without correlation (`tool_id_map` is not maintained) and without `detail` or `description` enrichment.

**Tool detail extraction** provides at-a-glance identification of what a tool call does. "Read /src/main.ts" is immediately useful; "Read" alone requires expanding the block to understand the call. The dispatch table `_TOOL_DETAIL_EXTRACTORS` is keyed by tool name:

| Tool | Detail Extracted |
|------|-----------------|
| `Read`, `Write`, `Edit` | File path from `file_path` input (front-ellipsed to 40 chars) |
| `Grep`, `Glob` | Pattern from `pattern` input (truncated to 60 chars) |
| `Bash` | First line of `command` input (if longer than 60 chars, truncated to first 57 chars + `...` suffix, producing a 60-char result) |
| `Skill` | Skill name from `skill` input |
| `mcp__plugin_repomix-mcp_repomix__file_system_read_file` | File path from `file_path` input (front-ellipsed to 40 chars) |
| Other | Empty string |

**Front-ellipsing:** `_front_ellipse_path()` truncates from the front: `/a/b/c/d/file.ts` becomes `...c/d/file.ts` when exceeding `max_len`. Front-ellipsing is used for file paths because the filename at the end is more informative than the root directory at the start -- users need to see *which file*, not *which filesystem root*.

#### `ToolResultBlock`
A `tool_result` content block from a message.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `size` | `int` | `0` | Line count of result text |
| `is_error` | `bool` | `False` | Whether the tool reported an error |
| `msg_color_idx` | `int` | `0` | Color index (from correlated ToolUseBlock, or message index fallback) |
| `tool_use_id` | `str` | `""` | ID for correlation |
| `tool_name` | `str` | `""` | Tool name (from correlated ToolUseBlock; empty if not correlated) |
| `detail` | `str` | `""` | Copied from correlated ToolUseBlock |
| `content` | `str` | `""` | Actual result text |
| `tool_input` | `dict` | `{}` | From correlated ToolUseBlock |

**Produced by:** `_format_tool_result_content()` (Anthropic format only). Content is extracted from the API's `content` field, which may be a string, a list of `{type: "text", text: "..."}` parts (text parts are concatenated), or any other JSON-serializable value (serialized with `json.dumps()`). The OpenAI format does not produce `ToolResultBlock` -- tool results appear as `role="tool"` messages containing `TextContentBlock`.

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
Tool use start during streaming, or tool use in complete responses.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | `""` | Tool name |

**Note:** Also used in `format_complete_response()` for tool_use content blocks (not just streaming). Carries only the tool name, not the full detail/input of `ToolUseBlock`.

#### `TextDeltaBlock`
A text delta from streaming response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content` | `str` | `""` | The delta text |
| `show_during_streaming` | `bool` | `True` | Overrides base default |

**Category:** Set dynamically at construction time to `Category.ASSISTANT`. The static `BLOCK_CATEGORY` mapping has no entry for `TextDeltaBlock`, so the category must be set on the block instance.

**Produced by:** `format_response_event()` for `TextDeltaEvent` SSE events. Only produced when the delta text is non-empty. Multiple deltas accumulate during streaming, then are consolidated into a single `TextContentBlock` at finalization (handled by the widget layer, not the formatting layer).

#### `StopReasonBlock`
Stop reason from `message_delta`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `reason` | `str` | `""` | e.g., `"end_turn"`, `"tool_use"`, `"max_tokens"` |

**Produced by:** `format_response_event()` for `MessageDeltaEvent` (only when `stop_reason != StopReason.NONE`). Also produced by `format_complete_response()` unconditionally (may be empty string). In OpenAI format, `format_openai_complete_response()` maps `finish_reason` from `choices[].finish_reason`.

#### `ResponseUsageBlock`
Actual token usage from the API response.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `input_tokens` | `int` | `0` | Fresh input tokens |
| `output_tokens` | `int` | `0` | Output tokens generated |
| `cache_read_tokens` | `int` | `0` | Input tokens served from cache (from `cache_read_input_tokens`) |
| `cache_creation_tokens` | `int` | `0` | Input tokens written to cache (from `cache_creation_input_tokens`) |
| `model` | `str` | `""` | Model name |

**Produced by:** `format_complete_response()`, always (renderer handles zeros). Not produced by `format_openai_complete_response()` -- OpenAI usage format differs and is not currently mapped.

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
2. `tool_descriptions` is extracted from the request body via `_update_tool_descriptions()` (before formatting, so ToolUseBlock can read it)
3. `format_request()` or `format_openai_request()` runs (reads state, does not mutate)
4. `current_session` is updated via `_update_session_id()` (after formatting, so NewSessionBlock emission sees the old value)

### 2. Provider Dispatch

The provider string determines which formatter runs. Provider specs are looked up via `cc_dump.providers.get_provider_spec(provider)`, which returns a spec with a `protocol_family` field (`"anthropic"` or `"openai"`) and a `display_name` field.

| Protocol Family | Request Formatter | Response Formatter |
|-----------------|-------------------|-------------------|
| `anthropic` | `format_request()` | `format_complete_response()` |
| `openai` | `format_openai_request()` | `format_openai_complete_response()` |

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
        SkillDefChild * N               # Skill tool only
        AgentDefChild * N               # Task tool only
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
        ThinkingBlock * N
        ImageBlock * N
        UnknownTypeBlock * N
NewlineBlock
```

### 4. Post-Processing (Anthropic Only)

After all blocks are created, `format_request()` walks the entire tree and:
- Calls `populate_content_regions()` on every block (idempotent)
- Stamps `session_id` on every block (including children)

The OpenAI request path does **not** perform this post-processing step. Content regions are not populated, and `session_id` is not stamped on blocks.

### 5. Cache Zone Annotation

When `cache_zones` is provided (from `analysis.compute_cache_zones()`), the `metadata["cache"]` field is set on container blocks:
- `ToolDefsSection` gets `cache_zones["tools"].value`
- `SystemSection` gets `cache_zones["system"].value`
- `MessageBlock` at index `i` gets `cache_zones["message:{i}"].value`

Cache zone values are `"cached"`, `"cache write"`, or `"fresh"` (from the `CacheZone` enum). Cache zones are only passed to the Anthropic request formatter.

---

## User Text Decomposition

User messages undergo special parsing to identify injected configuration and hooks. This is critical because Claude Code injects CLAUDE.md files, system reminders, and hook outputs into user messages, and making these visible is a core cc-dump feature.

### Detection Pipeline

`_format_user_text_content()` runs the segmentation parser on the raw text, then classifies each segment:

1. **XML blocks with hook tags** (`<system-reminder>`, `<user-prompt-submit-hook>`) become `HookOutputBlock` with the inner content extracted (text between the open and close tags).

2. **XML blocks with other tags** become `ConfigContentBlock` with the tag name as `source` and the full XML text (including tags) as `content`.

3. **Non-XML segments** (MD, CODE_FENCE, MD_FENCE) are passed to `_append_text_or_config_segments()`, which scans for `"Contents of ... CLAUDE.md"` or `"Contents of ... AGENTS.md"` patterns using `_CONFIG_SOURCE_RE`. Matched regions become `ConfigContentBlock` (source = file path, content = text following the header up to the next header); unmatched text becomes `TextContentBlock`.

4. **Empty result fallback:** If segmentation produces no blocks at all, the entire text is wrapped in a single `TextContentBlock`.

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
HookOutputBlock(hook_name="system-reminder", content="\nContents of /home/user/.claude/CLAUDE.md:\nAlways use TypeScript.\n")
TextContentBlock(content="Here is my actual question.\n")
```

Note: The `HookOutputBlock.content` is the inner text between `<system-reminder>` and `</system-reminder>`, including leading/trailing whitespace. The outer tags are stripped.

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

System prompts from `body.system` are converted to plain `TextContentBlock` instances inside a `SystemSection` container by `_make_system_prompt_children()`. The system field may be:

- A string -- produces one `TextContentBlock` (if non-empty)
- A list of dicts `{text: "...", type: "text"}` -- each non-empty `text` value produces one `TextContentBlock`
- A list of other values -- each is coerced to string

All system `TextContentBlock` instances get `category=Category.SYSTEM` and `indent="    "`.

**Content tracking is permanently absent.** ARCHITECTURE.md historically described a content-hashing system where system prompt sections would be tracked across requests with SHA256 hashes, color-coded tags (`[sp-1]`, `[sp-2]`), and unified diffs for changed content. This feature was never implemented and has been definitively removed from the design. There is no `TrackedContentBlock`, no hash computation on system prompt text, and no diff generation anywhere in the codebase. The `_make_system_prompt_children()` function explicitly states "no cross-request tracking" in its docstring. System prompts are rendered as plain text without any cross-request comparison. The `ProviderRuntimeState` carries no system prompt history -- only `request_counter`, `current_session`, and `tool_descriptions`.

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

**Lookup phase:** When a `tool_result` content block is formatted, its `tool_use_id` is looked up in the map. If found, the result block inherits the tool's name, color index, detail string, and input dict. If not found (orphaned result), the block gets: `tool_name=""`, `detail=""`, `tool_input={}`, and `msg_color_idx` falls back to `msg_index % MSG_COLOR_CYCLE`.

### Color Assignment

Tool colors use a 6-color cycle (`MSG_COLOR_CYCLE = 6`). Each `tool_use` block gets the next color in sequence (modulo 6). The corresponding `tool_result` block gets the same color index, creating visual pairing. The color counter persists across messages within a single request (not reset between messages).

### Correlation Scope

Tool correlation only operates in the Anthropic request formatter. The OpenAI request formatter does not maintain a `tool_id_map` and does not produce `ToolResultBlock` at all -- OpenAI tool results appear as `role="tool"` messages containing plain `TextContentBlock`.

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

System prompts and user messages contain a mix of markdown text, fenced code blocks, and XML tags. Treating the entire text as one opaque blob makes it impossible to collapse XML sections independently or apply syntax highlighting to code fences. Segmentation identifies the structural regions so the rendering layer can handle each appropriately, and so the formatting layer can decompose user text into hook/config/text blocks.

### The Segmentation Algorithm

`segmentation.segment()` performs a single linear scan with document-order precedence. At each position, whichever structure (XML open or fence open) starts earliest wins, and its span is opaque (content inside is not re-scanned). At the same position, XML is preferred over fences.

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
    info: str | None     # None for md_fence, first whitespace-delimited token for code_fence
    inner_span: Span     # Content between opening and closing fence lines
```

Fence closing rules: same marker character, length >= opening length, on its own line (optional leading/trailing whitespace).

### XmlBlockMeta

```
XmlBlockMeta
    tag_name: str
    start_tag_span: Span   # From start of tag to after '>'
    end_tag_span: Span     # From start of '</tag>' to after '>'
    inner_span: Span       # Content between open tag's '>' and close tag's '</'
```

### XML Parsing Forms

Three forms of XML blocks are recognized:

- **Form A:** `<tag>content after open tag\n...\n</tag>` (content starts on same line as open tag)
- **Form B:** `<tag>\ncontent\n</tag>` (tags on their own lines)
- **Form C:** `<tag>content</tag>` (single line)

For multi-line closing (Forms A & B), the parser first tries a strict match (closing tag on its own line), then falls back to a loose match (closing tag anywhere).

Comments (`<!--`), processing instructions (`<?`), CDATA (`<!`), closing tags (`</`), and self-closing tags (`/>`) are excluded. Tag names follow the pattern `[A-Za-z_][\w:.\-]*` and may include attributes.

### Error Handling

Unclosed fences and unclosed XML tags produce `ParseError` entries but do not halt parsing:

```
ParseError
    kind: ParseErrorKind   # UNCLOSED_FENCE or UNCLOSED_XML
    span: Span             # Location of the unclosed structure
    details: str           # Human-readable description
```

- Unclosed fences: the fence extends to end of text (the entire remaining content is claimed)
- Unclosed XML tags: the open tag line is skipped (parsing advances past the line)

### Tag Visibility Rewriting

Two utility functions handle XML tag visibility in markdown rendering:

- `wrap_tags_in_backticks(text)` -- Wraps bare `<tag>` occurrences in backticks so they render visibly in Rich's Markdown widget (otherwise they'd be treated as HTML and hidden). Tags already inside backticks are left alone.
- `wrap_tags_outside_fences(text)` -- Same, but skips content inside fenced code regions (fences are handled natively by the markdown renderer). Used for xml_block inner content which may contain code fences.

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

`markers_for_block(block)` dispatches to classifiers by block class name via `_CLASSIFIERS`:

| Block Type | Classifier |
|-----------|-----------|
| `ConfigContentBlock` | Checks `source` for "claude.md" (case-insensitive) |
| `HookOutputBlock` | Always `hook`; content scanned for skill/tool patterns |
| `TextContentBlock` | Only user-category blocks: content scanned for claude.md, skill, and tool patterns |
| `ToolUseBlock` | `name == "Skill"` yields `skill_send` |
| `ToolDefsSection` | `tool_count > 0` yields `tool_use_list` |

All other block types return no markers.

### Display vs. Navigation Markers

`display_markers_for_block()` filters to a subset intended for inline badges: `claude_md`, `skill_consideration`, `skill_send`, `tool_use_list`. The `hook` marker is used for navigation but not displayed as a badge.

### Location Collection

`collect_special_locations(turns, marker_key)` walks all completed turns (skipping streaming turns via `is_streaming` check), traverses block trees in pre-order including children, and collects `SpecialLocation` entries:

```
SpecialLocation
    marker: SpecialMarker   # key + label
    turn_index: int         # Index in the turns list
    block_index: int        # Hierarchical block index (top-level block index, preserved for children)
    block: object           # Reference to the actual block
```

When `marker_key="all"` (default), all markers are collected. When a specific key is passed, only locations with that marker key are returned.

---

## Response Formatting

### Streaming Responses

During streaming, `format_response_event()` dispatches on SSE event type via `_RESPONSE_EVENT_FORMATTERS`:

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

Unrecognized event types produce no blocks (the default lambda returns `[]`).

`TextDeltaBlock` is the only block with `show_during_streaming=True` by default. Multiple deltas accumulate during streaming and are consolidated into a single `TextContentBlock` at finalization (handled by the widget layer, not the formatting layer).

### Complete Responses (Anthropic)

`format_complete_response()` handles non-streaming (or replay) responses. It produces:

```
StreamInfoBlock(model=...)
MessageBlock(role="assistant")
    TextContentBlock * N        # from content[].type=="text"
    StreamToolUseBlock * N      # from content[].type=="tool_use" (name only)
    ThinkingBlock * N           # from content[].type=="thinking"
StopReasonBlock(reason=...)     # always produced (may be empty)
ResponseUsageBlock(...)         # always produced (renderer handles zeros)
```

The `MessageBlock` container wraps content children for structural consistency with request-side formatting. Content block dispatch uses `_COMPLETE_RESPONSE_FACTORIES`:
- `text` -> `TextContentBlock` (category ASSISTANT, only if non-empty)
- `tool_use` -> `StreamToolUseBlock` (name only)
- `thinking` -> `ThinkingBlock` (category THINKING, only if non-empty)

Usage fields are read from the response's `usage` object. `None` usage is coerced to `{}`. The cache fields use Anthropic's naming: `cache_read_input_tokens` and `cache_creation_input_tokens`.

### Complete Responses (OpenAI)

`format_openai_complete_response()` follows the same structural pattern but parses from `choices[].message` format:

```
StreamInfoBlock(model=...)
MessageBlock(role="assistant")
    TextContentBlock * N        # from message.content
    ToolUseBlock * N            # from message.tool_calls[].function
StopReasonBlock(reason=...)     # from choices[].finish_reason
```

Differences from Anthropic:
- Tool uses produce `ToolUseBlock` (not `StreamToolUseBlock`), with `tool_input` parsed from JSON `arguments`
- No `ResponseUsageBlock` is produced
- No `ThinkingBlock` support
- `finish_reason` is taken from the first choice that has one

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
| Compound tools | Skill/Task parsed into children | Not parsed (no compound tool support) |
| Tool use (request) | `content[].{type: "tool_use", id, name, input}` | `message.tool_calls[].{id, function: {name, arguments}}` |
| Tool result (request) | `content[].{type: "tool_result", tool_use_id, content}` -> `ToolResultBlock` | `{role: "tool", tool_call_id, content}` -> `TextContentBlock` in `MessageBlock` |
| Tool correlation | `tool_id_map` links use/result within request | No correlation |
| Tool detail enrichment | File paths, commands, patterns extracted | Not extracted |
| Tool descriptions | Populated from `state.tool_descriptions` | Not populated |
| User text decomposition | Hook/config/text splitting | Not performed (plain `TextContentBlock`) |
| Header label | `"REQUEST #N"` | `"REQUEST #N (ProviderName)"` |
| Session tracking | `NewSessionBlock` + session_id stamping | Neither |
| Content regions | Populated on all blocks | Not populated |
| Cache zones | `metadata["cache"]` on containers | Not supported |
| Response content | `content[].{type, text/thinking/tool_use}` | `choices[].message.{content, tool_calls}` |
| Response usage | `ResponseUsageBlock` produced | Not produced |
| Tool use (response) | `StreamToolUseBlock` (name only) | `ToolUseBlock` (with parsed input) |

Despite these differences, both paths produce the same IR block types. The OpenAI path is intentionally simpler -- it provides basic structural formatting without the enrichment features of the Anthropic path.
