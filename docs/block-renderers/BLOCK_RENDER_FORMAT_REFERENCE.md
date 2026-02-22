# Block Render Format Reference

Authoritative reference for every FormattedBlock type: what it is, which filter category controls it, and exactly what it produces under each VisState.

## High Level Goals

The high level goals of this block rendering system are:
- Instantaneous rendering
- Searchable
- Progressive disclosure
- Strong UX focus

The goals for each VisState (of which 5 are currently defined, see next section):
- Hidden: the block is completely hidden (no visibility)
  - This may change to displaying a single line to indicate a block exists, or that might become a 6th state
- Summary Collapsed
  - Shows a short glanceable summary of the most critical information
  - Potentially use side-channel Claude summary here
- Summary Expanded
  - Shows a detailed summary of an expanded range of information
  - Potentially use side-channel Claude summary here
- Full Collapsed
  - Shows a snippet of the full content
- Full Expanded
  - Shows the full content
  - These can be extremely long

The top goal of this core feature is that we do NOT simply 'reuse the same renderers' for multiple levels.  That defeats the entire point of this system.
The point of the system is to give users options that enables them to see the info they want at a variety of levels of detail, so they can get the gist or dig in as they need.

Keeping that in mind, here are some general rules or guidelines:
- Note: these mainly apply to content blocks that contain actual content, and aren't as strict for things like headers, new session block, role blocks, or other blocks which are structural
  - If we CAN do something to improve usability, great. But we must balance consistency and not have wildly different headers at different levels. Differences should be much more subtle for blocks that serve as markers of ones location within the data
- For everything that contains actual content 
  - We should never, or almost never, be reusing the same renderer for both summary and full views at any level
    - A summary is different by definition from the thing it summarizes.  a summary that is idential to the thing it's summarizing is not a summary
  - We should strive for consistency between block types as well
    - a collapsed summary should not be 90 lines on one block type and a single line on another
    - We probably want something like 2-3 lines on a collapsed summary, 8 or less lines on a full summary, 5 or less lines on a collapsed full, and the expanded full is currently always the entire content
- Rule: Expanded Full is always the full content
  - Caveat: Blocks are heirarchical, and often contain blocks within other categories.  A block at 'full expanded' may contain blocks that are at 'collapsed summary'.  this is not a contradiction, this is by design.  When a user
    wants to see 'all user blocks at full expanded' but has the 'tool' category hidden or at 'collapsed summary', they have intentionally gotten the tool blocks out of the way so they can use pure user blocks
    Users might also collapse nested blocks within the same category intentionally.  Maybe they want all giant markdown files collapsed within user blocks, which are at full expanded.  Again, this is not a contradiction.  We provide the flexibility to show the data users choose and get irrelevant data out of thier way.  this is a good thing

System, User, and Assistant blocks:
- Each of these blocks should have their inner text content rendered identically
- They contain a nested mix of XML, Markdown, and fenced code blocks (and potentially unfenced code blocks)
- These are the most complicated blocks to render due to this (we must parse this out so we can collapse indiviudal sections)
- these three should reuse the SAME renderer for "expanded full" and "probably collapsed full".  SUMMARIES should likely differ

**Critical: the document below is WHAT EXISTS TODAY.  We will be updating it to reflect how we WANT the app to work on an ongoing basis.  This is NOT a reference document YET.**

## VisState

`VisState(visible, full, expanded)` — three booleans. Five states cycle in order:

| Shorthand | VisState | Post-render truncation | Gutter arrow |
|-----------|----------|----------------------|--------------|
| **Hidden** | `(False, *, *)` | 0 lines (not rendered) | — |
| **SC** (Summary Collapsed) | `(True, False, False)` | max 4 lines | `▷` |
| **SE** (Summary Expanded) | `(True, False, True)` | unlimited | `▽` |
| **FC** (Full Collapsed) | `(True, True, False)` | max 4 lines | `▶` |
| **FE** (Full Expanded) | `(True, True, True)` | unlimited | `▼` |

---

## Region Default Expansion Policies

`TextContentBlock` segmented regions use kind-specific default expansion when no explicit `ViewOverrides` value is set:

- `code_fence`: expanded when line count `<= CC_DUMP_CODE_FENCE_DEFAULT_EXPANDED_MAX_LINES` (default `12`), otherwise collapsed.
- `xml_block`: expanded when line count `<= CC_DUMP_XML_BLOCK_DEFAULT_EXPANDED_MAX_LINES` (default `10`), otherwise collapsed.
- `md_fence`: expanded when line count `<= CC_DUMP_MD_FENCE_DEFAULT_EXPANDED_MAX_LINES` (default `14`), otherwise collapsed.

Explicit region overrides still win:

- `expanded = False` forces collapsed.
- `expanded = True` forces expanded.
- `expanded = None` uses the default policy above.

---

## Turn Framing

Blocks that delimit and label API request/response turns.

### SeparatorBlock — `METADATA`

Horizontal rule drawn between turns. Visual boundary only, no data content. Character is `─` (heavy) or `┄` (light) based on `block.style`. Style: `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#separatorblock-hidden-examples) |
| SC | `_render_separator` | Horizontal rule | [examples](#separatorblock-summary-collapsed-examples) |
| SE | `_render_separator` | Horizontal rule | [examples](#separatorblock-summary-expanded-examples) |
| FC | `_render_separator` | Horizontal rule | [examples](#separatorblock-full-collapsed-examples) |
| FE | `_render_separator` | Horizontal rule | [examples](#separatorblock-full-expanded-examples) |

#### SeparatorBlock Hidden Examples
No output produced.

#### SeparatorBlock Summary Collapsed Examples
#### SeparatorBlock Summary Expanded Examples
#### SeparatorBlock Full Collapsed Examples
#### SeparatorBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
──────────────────────────────────────────────────────────────────────
```

---

### HeaderBlock — `METADATA`

Labels the start of a request or response within a turn. Request label from `block.label`, styled `bold {info}`. Response label is `bold {success}`. Timestamp is `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#headerblock-hidden-examples) |
| SC | `_render_header` | Turn label + timestamp | [examples](#headerblock-summary-collapsed-examples) |
| SE | `_render_header` | Turn label + timestamp | [examples](#headerblock-summary-expanded-examples) |
| FC | `_render_header` | Turn label + timestamp | [examples](#headerblock-full-collapsed-examples) |
| FE | `_render_header` | Turn label + timestamp | [examples](#headerblock-full-expanded-examples) |

#### HeaderBlock Hidden Examples
No output produced.

#### HeaderBlock Summary Collapsed Examples
#### HeaderBlock Summary Expanded Examples
#### HeaderBlock Full Collapsed Examples
#### HeaderBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
 REQUEST 5  (2024-01-15 14:30:00)
```
```
 RESPONSE  (2024-01-15 14:30:01)
```

---

### RoleBlock — `None` (uses `block.category`: USER, ASSISTANT, or SYSTEM)

Labels a message's role within the conversation array. One per message. Role uses `ROLE_STYLES` (`bold {user}`, `bold {assistant}`, `bold {system}`). Timestamp is `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#roleblock-hidden-examples) |
| SC | `_render_role` | Role label + timestamp | [examples](#roleblock-summary-collapsed-examples) |
| SE | `_render_role` | Role label + timestamp | [examples](#roleblock-summary-expanded-examples) |
| FC | `_render_role` | Role label + timestamp | [examples](#roleblock-full-collapsed-examples) |
| FE | `_render_role` | Role label + timestamp | [examples](#roleblock-full-expanded-examples) |

#### RoleBlock Hidden Examples
No output produced.

#### RoleBlock Summary Collapsed Examples
#### RoleBlock Summary Expanded Examples
#### RoleBlock Full Collapsed Examples
#### RoleBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
USER  14:30:00
ASSISTANT  14:30:01
```

---

### NewlineBlock — `None` (always visible, no category filtering)

Empty line for visual spacing between blocks. No content.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#newlineblock-hidden-examples) |
| SC | `_render_newline` | Empty line | [examples](#newlineblock-summary-collapsed-examples) |
| SE | `_render_newline` | Empty line | [examples](#newlineblock-summary-expanded-examples) |
| FC | `_render_newline` | Empty line | [examples](#newlineblock-full-collapsed-examples) |
| FE | `_render_newline` | Empty line | [examples](#newlineblock-full-expanded-examples) |

#### NewlineBlock Hidden Examples
No output produced.

#### NewlineBlock Summary Collapsed Examples
#### NewlineBlock Summary Expanded Examples
#### NewlineBlock Full Collapsed Examples
#### NewlineBlock Full Expanded Examples

All visible states produce an empty line.

---

### NewSessionBlock — `METADATA`

Prominent 3-line banner marking when a new Claude Code session ID appears in the traffic. Border and "NEW SESSION:" are `bold {info}`, session ID is `bold`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#newsessionblock-hidden-examples) |
| SC | `_render_new_session` | Session banner | [examples](#newsessionblock-summary-collapsed-examples) |
| SE | `_render_new_session` | Session banner | [examples](#newsessionblock-summary-expanded-examples) |
| FC | `_render_new_session` | Session banner | [examples](#newsessionblock-full-collapsed-examples) |
| FE | `_render_new_session` | Session banner | [examples](#newsessionblock-full-expanded-examples) |

#### NewSessionBlock Hidden Examples
No output produced.

#### NewSessionBlock Summary Collapsed Examples
#### NewSessionBlock Summary Expanded Examples
#### NewSessionBlock Full Collapsed Examples
#### NewSessionBlock Full Expanded Examples

All visible states produce identical output (3 lines, fits within 4-line truncation):

```
════════════════════════════════════════
 NEW SESSION: a1b2c3d4-e5f6-7890-abcd-ef1234567890
════════════════════════════════════════
```

---

## Message Content

The actual text exchanged between user, assistant, and system — the core payload of the API traffic.

### TextContentBlock — `None` (uses `block.category`: USER, ASSISTANT, or SYSTEM)

The primary content block. Holds user prompts, assistant responses, or system instructions. For USER/ASSISTANT/SYSTEM categories, content is rendered as segmented Markdown with Pygments syntax highlighting on code fences and palette-colored XML tags. Other categories render as indented plain text.

When `block.content_regions` is populated (content has XML blocks or code fences), takes the region rendering path — each segment renders independently with per-region collapse/expand for XML blocks.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#textcontentblock-hidden-examples) |
| SC | `_render_text_content` | Full Markdown, truncated to 4 lines | [examples](#textcontentblock-summary-collapsed-examples) |
| SE | `_render_text_content` | Full Markdown, unlimited | [examples](#textcontentblock-summary-expanded-examples) |
| FC | `_render_text_content` | Full Markdown, truncated to 4 lines | [examples](#textcontentblock-full-collapsed-examples) |
| FE | `_render_text_content` | Full Markdown, unlimited | [examples](#textcontentblock-full-expanded-examples) |

Styles: Rich Markdown rendering with theme code highlighting. XML tags use palette-derived colors. Collapsed XML regions show `▷` arrow with content preview (max 60 chars). Expanded XML regions show `▽` arrow.

#### TextContentBlock Hidden Examples
No output produced.

#### TextContentBlock Summary Collapsed Examples

```
I'll help you fix that bug. Here's the change:

def calculate_total(items):
    return sum(item.price for item in items)
    ··· 12 more lines
```

#### TextContentBlock Summary Expanded Examples

Full Markdown content, all lines shown:

```
I'll help you fix that bug. Here's the change:

def calculate_total(items):
    return sum(item.price for item in items)

This replaces the manual loop with a generator expression.
The function now handles empty lists correctly by returning 0.

Let me also update the tests:

def test_calculate_total():
    items = [Item(price=10), Item(price=20)]
    assert calculate_total(items) == 30
    assert calculate_total([]) == 0
```

#### TextContentBlock Full Collapsed Examples

Same as Summary Collapsed — identical renderer and identical 4-line truncation:

```
I'll help you fix that bug. Here's the change:

def calculate_total(items):
    return sum(item.price for item in items)
    ··· 12 more lines
```

#### TextContentBlock Full Expanded Examples

Same as Summary Expanded — identical renderer, unlimited.

**Region rendering path** (when content_regions populated):

Expanded XML region:
```
▽ <search_results>
Result 1: Found matching function in utils.py line 42
Result 2: Similar pattern in helpers.py line 15
</search_results>
```

Collapsed XML region:
```
▷ <search_results>Result 1: Found matching function in utils.py li…</search_results>
```

---

### TextDeltaBlock — `None` (uses `block.category`, typically ASSISTANT)

Streaming-mode equivalent of TextContentBlock. Holds partial text fragments arriving via SSE. Replaced by TextContentBlock when the turn completes. Truncation is always skipped during streaming (`is_streaming=True`).

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#textdeltablock-hidden-examples) |
| SC | `_render_text_delta` | Segmented Markdown | [examples](#textdeltablock-summary-collapsed-examples) |
| SE | `_render_text_delta` | Segmented Markdown | [examples](#textdeltablock-summary-expanded-examples) |
| FC | `_render_text_delta` | Segmented Markdown | [examples](#textdeltablock-full-collapsed-examples) |
| FE | `_render_text_delta` | Segmented Markdown | [examples](#textdeltablock-full-expanded-examples) |

#### TextDeltaBlock Hidden Examples
No output produced.

#### TextDeltaBlock Summary Collapsed Examples
#### TextDeltaBlock Summary Expanded Examples
#### TextDeltaBlock Full Collapsed Examples
#### TextDeltaBlock Full Expanded Examples

All visible states identical (truncation skipped during streaming):

```
I'm working on implementing the fix. Let me start by reading
the relevant files...
```

Styles: Rich Markdown rendering with code theme.

---

### ImageBlock — `None` (uses `block.category` from parent message)

Represents an image content block in the API payload. Shows media type only — no image rendering. Style: `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#imageblock-hidden-examples) |
| SC | `_render_image` | Media type label | [examples](#imageblock-summary-collapsed-examples) |
| SE | `_render_image` | Media type label | [examples](#imageblock-summary-expanded-examples) |
| FC | `_render_image` | Media type label | [examples](#imageblock-full-collapsed-examples) |
| FE | `_render_image` | Media type label | [examples](#imageblock-full-expanded-examples) |

#### ImageBlock Hidden Examples
No output produced.

#### ImageBlock Summary Collapsed Examples
#### ImageBlock Summary Expanded Examples
#### ImageBlock Full Collapsed Examples
#### ImageBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  [image: image/png]
```

---

### ThinkingBlock — `THINKING`

Extended thinking content from the assistant. Contains the model's reasoning text, rendered dim/italic to visually distinguish from regular output.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#thinkingblock-hidden-examples) |
| SC | `_render_thinking_summary` | Line count only | [examples](#thinkingblock-summary-collapsed-examples) |
| SE | `_render_thinking_summary` | Line count only | [examples](#thinkingblock-summary-expanded-examples) |
| FC | `_render_thinking` | Full thinking content, truncated to 4 lines | [examples](#thinkingblock-full-collapsed-examples) |
| FE | `_render_thinking` | Full thinking content, unlimited | [examples](#thinkingblock-full-expanded-examples) |

Styles: `[thinking]` is `bold dim`, content is `dim italic`, line count is `dim`.

#### ThinkingBlock Hidden Examples
No output produced.

#### ThinkingBlock Summary Collapsed Examples

```
[thinking] (42 lines)
```

#### ThinkingBlock Summary Expanded Examples

Same as SC:

```
[thinking] (42 lines)
```

#### ThinkingBlock Full Collapsed Examples

```
[thinking] Let me analyze this problem step by step.
First, I need to understand the data flow through the
rendering pipeline. The FormattedBlock IR is created by
formatting.py and then passed to rendering.py which
    ··· 38 more lines
```

#### ThinkingBlock Full Expanded Examples

Same content as FC, all lines shown (no truncation).

---

## Request Metadata

Information about the API request/response envelope — model, parameters, headers, token budget, stop reason.

### MetadataBlock — `METADATA`

One-line summary of request parameters: model name, max_tokens, stream flag, tool count, and parsed user/account/session IDs from the API's metadata.user_id field. Entire line is `dim`, model name is `bold`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#metadatablock-hidden-examples) |
| SC | `_render_metadata` | Model + params one-liner | [examples](#metadatablock-summary-collapsed-examples) |
| SE | `_render_metadata` | Model + params one-liner | [examples](#metadatablock-summary-expanded-examples) |
| FC | `_render_metadata` | Model + params one-liner | [examples](#metadatablock-full-collapsed-examples) |
| FE | `_render_metadata` | Model + params one-liner | [examples](#metadatablock-full-expanded-examples) |

#### MetadataBlock Hidden Examples
No output produced.

#### MetadataBlock Summary Collapsed Examples
#### MetadataBlock Summary Expanded Examples
#### MetadataBlock Full Collapsed Examples
#### MetadataBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  model: claude-sonnet-4-5-20250929 | max_tokens: 8192 | stream: true | tools: 42 | user: a1b2c3.. | account: d4e5f6g7 | session: h8i9j0k1
```

---

### HttpHeadersBlock — `METADATA`

HTTP headers from the request or response. Request variant shows outgoing headers; response variant shows status code and all response headers.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#httpheadersblock-hidden-examples) |
| SC | `_render_http_headers_summary` | One-liner: status + header count + content-type | [examples](#httpheadersblock-summary-collapsed-examples) |
| SE | `_render_http_headers` | Full header listing, unlimited | [examples](#httpheadersblock-summary-expanded-examples) |
| FC | `_render_http_headers` | Full header listing, truncated to 4 lines | [examples](#httpheadersblock-full-collapsed-examples) |
| FE | `_render_http_headers` | Full header listing, unlimited | [examples](#httpheadersblock-full-expanded-examples) |

Styles: label is `bold {success}` (response) or `bold {info}` (request). Header keys are `dim {info}`, values are `dim`. Summary counts are `dim`.

#### HttpHeadersBlock Hidden Examples
No output produced.

#### HttpHeadersBlock Summary Collapsed Examples

```
  HTTP 200  (5 headers)  content-type: application/json
```

Request variant:
```
  Request Headers  (3 headers)  content-type: application/json
```

#### HttpHeadersBlock Summary Expanded Examples

```
  Response HTTP 200
    content-type: application/json
    x-request-id: req_abc123def456
    x-ratelimit-limit: 1000
    x-ratelimit-remaining: 999
    x-ratelimit-reset: 2024-01-15T15:00:00Z
```

#### HttpHeadersBlock Full Collapsed Examples

```
  Response HTTP 200
    content-type: application/json
    x-ratelimit-limit: 1000
    x-ratelimit-remaining: 999
    ··· 2 more lines
```

#### HttpHeadersBlock Full Expanded Examples

Same as Summary Expanded — both use full renderer with unlimited truncation.

---

### TurnBudgetBlock — `METADATA`

Token budget analysis for a turn. Estimates token breakdown across system prompt, tool definitions, conversation history, and tool results. Shows actual cache hit rates when response data is available.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#turnbudgetblock-hidden-examples) |
| SC | `_render_turn_budget_oneliner` | Total token count only | [examples](#turnbudgetblock-summary-collapsed-examples) |
| SE | `_render_turn_budget_oneliner` | Total token count only | [examples](#turnbudgetblock-summary-expanded-examples) |
| FC | `_render_turn_budget` | Full breakdown with cache info, truncated to 4 lines | [examples](#turnbudgetblock-full-collapsed-examples) |
| FE | `_render_turn_budget` | Full breakdown with cache info, unlimited | [examples](#turnbudgetblock-full-expanded-examples) |

Styles: "Context:" and "Cache:" are `bold`. Sys is `dim {info}`, tools is `dim {warning}`, conv is `dim {success}`. Cache-read is `dim {info}`, cache-created is `dim {warning}`, fresh is `dim`.

#### TurnBudgetBlock Hidden Examples
No output produced.

#### TurnBudgetBlock Summary Collapsed Examples

```
  Context: 45,200 tokens
```

#### TurnBudgetBlock Summary Expanded Examples

Same as SC:

```
  Context: 45,200 tokens
```

#### TurnBudgetBlock Full Collapsed Examples

```
  Context: 45,200 tokens | sys: 12,000 (27%) | tools: 8,500 (19%) | conv: 24,700 (55%)
    tool_use: 3,200 | tool_results: 5,300 (Read: 3,100, Bash: 1,200, Edit: 1,000)
    Cache: 38,000 read (84%) | 2,100 created | 5,100 fresh
```

(Typically 3 lines — fits within 4-line limit.)

#### TurnBudgetBlock Full Expanded Examples

Same content as FC (typically 3 lines, so truncation never applies).

---

### StopReasonBlock — `METADATA`

Shows the API's stop reason for a response (end_turn, max_tokens, tool_use, etc.). Style: `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#stopreasonblock-hidden-examples) |
| SC | `_render_stop_reason` | Stop reason label | [examples](#stopreasonblock-summary-collapsed-examples) |
| SE | `_render_stop_reason` | Stop reason label | [examples](#stopreasonblock-summary-expanded-examples) |
| FC | `_render_stop_reason` | Stop reason label | [examples](#stopreasonblock-full-collapsed-examples) |
| FE | `_render_stop_reason` | Stop reason label | [examples](#stopreasonblock-full-expanded-examples) |

#### StopReasonBlock Hidden Examples
No output produced.

#### StopReasonBlock Summary Collapsed Examples
#### StopReasonBlock Summary Expanded Examples
#### StopReasonBlock Full Collapsed Examples
#### StopReasonBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  stop: end_turn
```

---

### StreamInfoBlock — `METADATA`

Model name extracted from the `message_start` SSE event during streaming. Appears before content blocks while streaming is in progress. Style: `dim` base, model name is `bold`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#streaminfoblock-hidden-examples) |
| SC | `_render_stream_info` | Model name | [examples](#streaminfoblock-summary-collapsed-examples) |
| SE | `_render_stream_info` | Model name | [examples](#streaminfoblock-summary-expanded-examples) |
| FC | `_render_stream_info` | Model name | [examples](#streaminfoblock-full-collapsed-examples) |
| FE | `_render_stream_info` | Model name | [examples](#streaminfoblock-full-expanded-examples) |

#### StreamInfoBlock Hidden Examples
No output produced.

#### StreamInfoBlock Summary Collapsed Examples
#### StreamInfoBlock Summary Expanded Examples
#### StreamInfoBlock Full Collapsed Examples
#### StreamInfoBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  model: claude-sonnet-4-5-20250929
```

---

## System Prompt Tracking

Tracked system prompt sections with content-addressed change detection across turns.

### SystemLabelBlock — `SYSTEM`

Simple label that precedes system prompt content blocks. Style: `bold {system}`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#systemlabelblock-hidden-examples) |
| SC | `_render_system_label` | "SYSTEM:" label | [examples](#systemlabelblock-summary-collapsed-examples) |
| SE | `_render_system_label` | "SYSTEM:" label | [examples](#systemlabelblock-summary-expanded-examples) |
| FC | `_render_system_label` | "SYSTEM:" label | [examples](#systemlabelblock-full-collapsed-examples) |
| FE | `_render_system_label` | "SYSTEM:" label | [examples](#systemlabelblock-full-expanded-examples) |

#### SystemLabelBlock Hidden Examples
No output produced.

#### SystemLabelBlock Summary Collapsed Examples
#### SystemLabelBlock Summary Expanded Examples
#### SystemLabelBlock Full Collapsed Examples
#### SystemLabelBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
SYSTEM:
```

---

### TrackedContentBlock — `SYSTEM`

A content-addressed system prompt section (e.g., CLAUDE.md, tool instructions, project context). Assigned a color from the palette by tag ID. Tracks changes with status: "new" (first appearance), "ref" (unchanged since last turn), or "changed" (with unified diff).

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#trackedcontentblock-hidden-examples) |
| SC | `_render_tracked_content_title` | Tag ID + status + line count (no content) | [examples](#trackedcontentblock-summary-collapsed-examples) |
| SE | `_render_tracked_content_summary` | Tag-colored header + diff-aware content | [examples](#trackedcontentblock-summary-expanded-examples) |
| FC | `_render_tracked_content_full` | Raw Markdown content (no tags, no diffs), truncated to 4 lines | [examples](#trackedcontentblock-full-collapsed-examples) |
| FE | `_render_tracked_content_full` | Raw Markdown content, unlimited | [examples](#trackedcontentblock-full-expanded-examples) |

Styles: tag ID has `bold {fg} on {bg}` from palette. Diff uses `+`/`-` prefixes with color coding.

#### TrackedContentBlock Hidden Examples
No output produced.

#### TrackedContentBlock Summary Collapsed Examples

```
   CLAUDE.md  CHANGED (40 -> 42 lines)
   CLAUDE.md  NEW (42 lines)
   CLAUDE.md  (unchanged)
```

#### TrackedContentBlock Summary Expanded Examples

For `status="changed"` — tag header + unified diff:
```
   CLAUDE.md  CHANGED (40 -> 42 lines):
    + added line here
    - removed line here
      unchanged context line
```

For `status="new"` — tag header + full content as Markdown:
```
   CLAUDE.md  NEW (42 lines):
  # Document Title
  Content here...
```

For `status="ref"`:
```
   CLAUDE.md  (unchanged)
```

#### TrackedContentBlock Full Collapsed Examples

Raw Markdown content, no tag styling or diffs, truncated:
```
# Document Title
This is the full content of the tracked file.
It renders as Markdown without any tag styling
or diff information.
    ··· 38 more lines
```

#### TrackedContentBlock Full Expanded Examples

Same raw Markdown, all lines shown (no truncation).

---

### ConfigContentBlock — `None` (inherits parent category, typically USER)

A configuration file embedded in the user message (e.g., CLAUDE.md contents sent as user context). Shows source filename and content. Label is `bold dim`, content is `dim`, line count is `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#configcontentblock-hidden-examples) |
| SC | `_render_config_content_summary` | Source + line count | [examples](#configcontentblock-summary-collapsed-examples) |
| SE | `_render_config_content_summary` | Source + line count | [examples](#configcontentblock-summary-expanded-examples) |
| FC | `_render_config_content` | Source label + full content, truncated to 4 lines | [examples](#configcontentblock-full-collapsed-examples) |
| FE | `_render_config_content` | Source label + full content, unlimited | [examples](#configcontentblock-full-expanded-examples) |

#### ConfigContentBlock Hidden Examples
No output produced.

#### ConfigContentBlock Summary Collapsed Examples

```
[config: CLAUDE.md] (42 lines)
```

#### ConfigContentBlock Summary Expanded Examples

Same as SC:

```
[config: CLAUDE.md] (42 lines)
```

#### ConfigContentBlock Full Collapsed Examples

```
[config: CLAUDE.md] # CLAUDE.md
This file provides guidance to Claude Code when working
with code in this repository.
## What This Is
    ··· 38 more lines
```

#### ConfigContentBlock Full Expanded Examples

Same content as FC, all lines shown.

---

### HookOutputBlock — `None` (inherits parent category)

Output from a Claude Code hook (PreToolUse, PostToolUse, etc.) embedded in the user message. Shows hook name and output text. Label is `bold dim`, content is `dim`, line count is `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#hookoutputblock-hidden-examples) |
| SC | `_render_hook_output_summary` | Hook name + line count | [examples](#hookoutputblock-summary-collapsed-examples) |
| SE | `_render_hook_output_summary` | Hook name + line count | [examples](#hookoutputblock-summary-expanded-examples) |
| FC | `_render_hook_output` | Hook name + full output, truncated to 4 lines | [examples](#hookoutputblock-full-collapsed-examples) |
| FE | `_render_hook_output` | Hook name + full output, unlimited | [examples](#hookoutputblock-full-expanded-examples) |

#### HookOutputBlock Hidden Examples
No output produced.

#### HookOutputBlock Summary Collapsed Examples

```
[hook: PreToolUse] (5 lines)
```

#### HookOutputBlock Summary Expanded Examples

Same as SC:

```
[hook: PreToolUse] (5 lines)
```

#### HookOutputBlock Full Collapsed Examples

```
[hook: PreToolUse] Hook executed successfully.
Validated tool parameters.
Check passed: file path is within project.
Check passed: no destructive git commands.
    ··· 1 more lines
```

#### HookOutputBlock Full Expanded Examples

Same content as FC, all lines shown.

---

## Tool Definitions

The tool schemas sent in the API request — names, descriptions, parameters, and token estimates.

### ToolDefinitionsBlock — `TOOLS`

Aggregated view of all tool definitions in a request. Holds the full tool array with per-tool token estimates. Has four distinct renderers — one for each visible VisState.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#tooldefinitionsblock-hidden-examples) |
| SC | `_render_tool_defs_summary_collapsed` | Tool count + total tokens | [examples](#tooldefinitionsblock-summary-collapsed-examples) |
| SE | `_render_tool_defs_summary_expanded` | Two-column name/token listing | [examples](#tooldefinitionsblock-summary-expanded-examples) |
| FC | `_render_tool_defs_full_collapsed` | Comma-separated tool names | [examples](#tooldefinitionsblock-full-collapsed-examples) |
| FE | `_render_tool_def_region_parts` | Per-tool collapsible regions with descriptions and params | [examples](#tooldefinitionsblock-full-expanded-examples) |

#### ToolDefinitionsBlock Hidden Examples
No output produced.

#### ToolDefinitionsBlock Summary Collapsed Examples

Style: `dim`.

```
  42 tools / 15.2k tokens
```

#### ToolDefinitionsBlock Summary Expanded Examples

Header is `bold {info}`, token counts are `dim`, names left-aligned to max width.

```
  Tools (42 / 15.2k tokens):
    Bash                  523 tokens
    Read                  412 tokens
    Write                 389 tokens
    Edit                  445 tokens
    Grep                  356 tokens
    ...
```

#### ToolDefinitionsBlock Full Collapsed Examples

"Tools:" is `bold`, names are `dim`. Truncated to 100 chars with `...`.

```
  Tools: Bash, Read, Write, Edit, Grep, Glob, Task, WebFetch, WebSearch, ...
```

#### ToolDefinitionsBlock Full Expanded Examples

Each tool is a collapsible region. Header is `bold {info}`, `▽`/`▷` arrows are `bold {info}`, tool name is `bold`, tokens are `dim`, description is `dim italic`, param names are `bold dim` (`*` = required), types are `dim`.

```
  Tools: 42 definitions (15,200 tokens)
    ▽ Bash (523 tokens):
      Execute bash commands in the terminal
      command*: string
      timeout: number
    ▽ Read (412 tokens):
      Read a file from the filesystem
      file_path*: string
      offset: number
      limit: number
    ▷ Write (389 tokens): Write a file to the local filesystem...
```

---

### ToolDefBlock — `TOOLS`

A single tool definition within a hierarchical container. Shows tool name and token estimate. Name is `bold`, tokens are `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#tooldefblock-hidden-examples) |
| SC | `_render_tool_def` | Tool name + token count | [examples](#tooldefblock-summary-collapsed-examples) |
| SE | `_render_tool_def` | Tool name + token count | [examples](#tooldefblock-summary-expanded-examples) |
| FC | `_render_tool_def` | Tool name + token count | [examples](#tooldefblock-full-collapsed-examples) |
| FE | `_render_tool_def` | Tool name + token count | [examples](#tooldefblock-full-expanded-examples) |

#### ToolDefBlock Hidden Examples
No output produced.

#### ToolDefBlock Summary Collapsed Examples
#### ToolDefBlock Summary Expanded Examples
#### ToolDefBlock Full Collapsed Examples
#### ToolDefBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
Bash (523 tokens)
```

---

### SkillDefChild — `TOOLS`

A skill definition child block (tools that are Claude Code skills). Shows name and first 60 chars of description. Name is `bold`, description is `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#skilldefchild-hidden-examples) |
| SC | `_render_skill_def_child` | Skill name + description preview | [examples](#skilldefchild-summary-collapsed-examples) |
| SE | `_render_skill_def_child` | Skill name + description preview | [examples](#skilldefchild-summary-expanded-examples) |
| FC | `_render_skill_def_child` | Skill name + description preview | [examples](#skilldefchild-full-collapsed-examples) |
| FE | `_render_skill_def_child` | Skill name + description preview | [examples](#skilldefchild-full-expanded-examples) |

#### SkillDefChild Hidden Examples
No output produced.

#### SkillDefChild Summary Collapsed Examples
#### SkillDefChild Summary Expanded Examples
#### SkillDefChild Full Collapsed Examples
#### SkillDefChild Full Expanded Examples

All visible states produce identical output (1 line):

```
commit — "Create a git commit with a descriptive message based on st..."
```

---

### AgentDefChild — `TOOLS`

An agent definition child block (tools that are Claude Code agents). Same format as SkillDefChild. Name is `bold`, description is `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#agentdefchild-hidden-examples) |
| SC | `_render_agent_def_child` | Agent name + description preview | [examples](#agentdefchild-summary-collapsed-examples) |
| SE | `_render_agent_def_child` | Agent name + description preview | [examples](#agentdefchild-summary-expanded-examples) |
| FC | `_render_agent_def_child` | Agent name + description preview | [examples](#agentdefchild-full-collapsed-examples) |
| FE | `_render_agent_def_child` | Agent name + description preview | [examples](#agentdefchild-full-expanded-examples) |

#### AgentDefChild Hidden Examples
No output produced.

#### AgentDefChild Summary Collapsed Examples
#### AgentDefChild Summary Expanded Examples
#### AgentDefChild Full Collapsed Examples
#### AgentDefChild Full Expanded Examples

All visible states produce identical output (1 line):

```
Explore — "Fast agent specialized for exploring codebases. Use this..."
```

---

## Tool Usage

Tool calls from the assistant and their results — the back-and-forth of agentic tool use.

### ToolUseBlock — `TOOLS`

A tool call from the assistant. Contains tool name, input parameters, file path detail, and optional description. Has tool-specific rendering: Bash shows the command with syntax highlighting, Edit shows old/new line counts, other tools show a one-liner.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#tooluseblock-hidden-examples) |
| SC | `_render_tool_use_full` | Tool-specific full rendering, truncated to 4 lines | [examples](#tooluseblock-summary-collapsed-examples) |
| SE | `_render_tool_use_full` | Tool-specific full rendering, unlimited | [examples](#tooluseblock-summary-expanded-examples) |
| FC | `_render_tool_use_oneliner` | One-liner: tool name + detail + line count | [examples](#tooluseblock-full-collapsed-examples) |
| FE | `_render_tool_use_full_with_desc` | Tool-specific rendering + tool description | [examples](#tooluseblock-full-expanded-examples) |

Styles: `[Use: Name]` is `bold {msg_color}`, detail (file path) is `dim`. Bash command uses Syntax highlighting. Edit old/new counts use `{error}`/`{success}`. Description is `dim italic`.

#### ToolUseBlock Hidden Examples
No output produced.

#### ToolUseBlock Summary Collapsed Examples

Bash:
```
  [Use: Bash] (3 lines)
  $ git status --short
```

Edit:
```
  [Use: Edit] src/main.py (5 lines)
    - old (3 lines) / + new (5 lines)
```

Other tools (Read, Write, Grep, etc.):
```
  [Use: Read] src/main.py (1 lines)
```

#### ToolUseBlock Summary Expanded Examples

Same content as SC but unlimited (no truncation). All lines shown.

#### ToolUseBlock Full Collapsed Examples

```
  [Use: Bash] /path/to/dir (3 lines)
  [Use: Read] src/main.py (1 lines)
  [Use: Edit] src/main.py (5 lines)
```

#### ToolUseBlock Full Expanded Examples

Same as SE content, plus first line of tool description (max 120 chars):

Bash:
```
  [Use: Bash] (3 lines)
  $ git status --short
    Execute bash commands in the terminal
```

Other:
```
  [Use: Read] src/main.py (1 lines)
    Read a file from the local filesystem
```

---

### ToolResultBlock — `TOOLS`

The result returned from a tool call. Has tool-specific rendering: Read shows syntax-highlighted file content, Write/Edit shows a checkmark confirmation, Bash and other tools show dim content.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#toolresultblock-hidden-examples) |
| SC | `_render_tool_result_full` | Tool-specific full result, truncated to 4 lines | [examples](#toolresultblock-summary-collapsed-examples) |
| SE | `_render_tool_result_full` | Tool-specific full result, unlimited | [examples](#toolresultblock-summary-expanded-examples) |
| FC | `_render_tool_result_summary` | Header only (tool name + line count), no content | [examples](#toolresultblock-full-collapsed-examples) |
| FE | `_render_tool_result_full` | Tool-specific full result, unlimited | [examples](#toolresultblock-full-expanded-examples) |

Styles: `[Result: Name]` is `bold {msg_color}`, detail is `dim`, `✓` is `bold {success}`. Read content uses Syntax highlighting by file extension. Generic content is `dim`.

#### ToolResultBlock Hidden Examples
No output produced.

#### ToolResultBlock Summary Collapsed Examples

Read:
```
  [Result: Read] src/main.py (45 lines)
  def main():
      parser = argparse.ArgumentParser()
      parser.add_argument("--port", type=int)
    ··· 42 more lines
```

Write/Edit:
```
  [Result: Write] src/main.py (1 lines) ✓
```

Bash (generic):
```
  [Result: Bash] (12 lines)
  M  src/app.py
  M  src/utils.py
  ?? new_file.py
    ··· 8 more lines
```

#### ToolResultBlock Summary Expanded Examples

Same as SC but all lines shown (no truncation).

#### ToolResultBlock Full Collapsed Examples

```
  [Result: Bash] (12 lines)
  [Result: Read] src/main.py (45 lines)
  [Result: Edit] src/main.py (1 lines)
```

#### ToolResultBlock Full Expanded Examples

Same as Summary Expanded — full content shown.

---

### ToolUseSummaryBlock — `TOOLS`

Collapsed summary that replaces consecutive ToolUse/ToolResult pairs when the tools category is hidden. Shows aggregated tool call counts. Style: `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#toolusesummaryblock-hidden-examples) |
| SC | `_render_tool_use_summary` | Aggregated tool counts | [examples](#toolusesummaryblock-summary-collapsed-examples) |
| SE | `_render_tool_use_summary` | Aggregated tool counts | [examples](#toolusesummaryblock-summary-expanded-examples) |
| FC | `_render_tool_use_summary` | Aggregated tool counts | [examples](#toolusesummaryblock-full-collapsed-examples) |
| FE | `_render_tool_use_summary` | Aggregated tool counts | [examples](#toolusesummaryblock-full-expanded-examples) |

#### ToolUseSummaryBlock Hidden Examples
No output produced.

#### ToolUseSummaryBlock Summary Collapsed Examples
#### ToolUseSummaryBlock Summary Expanded Examples
#### ToolUseSummaryBlock Full Collapsed Examples
#### ToolUseSummaryBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  [used 5 tools: Bash 3x, Read 2x]
```

---

### StreamToolUseBlock — `TOOLS`

Streaming-mode placeholder for an in-progress tool call. Shows tool name during SSE streaming before the full ToolUseBlock is assembled. `[tool_use]` is `bold {info}`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#streamtooluseblock-hidden-examples) |
| SC | `_render_stream_tool_use` | Tool name label | [examples](#streamtooluseblock-summary-collapsed-examples) |
| SE | `_render_stream_tool_use` | Tool name label | [examples](#streamtooluseblock-summary-expanded-examples) |
| FC | `_render_stream_tool_use` | Tool name label | [examples](#streamtooluseblock-full-collapsed-examples) |
| FE | `_render_stream_tool_use` | Tool name label | [examples](#streamtooluseblock-full-expanded-examples) |

#### StreamToolUseBlock Hidden Examples
No output produced.

#### StreamToolUseBlock Summary Collapsed Examples
#### StreamToolUseBlock Summary Expanded Examples
#### StreamToolUseBlock Full Collapsed Examples
#### StreamToolUseBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  [tool_use] Bash
```

---

## Errors

Error conditions from the API or proxy. Always visible regardless of filter settings.

### ErrorBlock — `None` (always visible)

An HTTP error response from the Anthropic API. Shows status code and error type. Style: `bold {error}`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#errorblock-hidden-examples) |
| SC | `_render_error` | HTTP status + error type | [examples](#errorblock-summary-collapsed-examples) |
| SE | `_render_error` | HTTP status + error type | [examples](#errorblock-summary-expanded-examples) |
| FC | `_render_error` | HTTP status + error type | [examples](#errorblock-full-collapsed-examples) |
| FE | `_render_error` | HTTP status + error type | [examples](#errorblock-full-expanded-examples) |

#### ErrorBlock Hidden Examples
No output produced.

#### ErrorBlock Summary Collapsed Examples
#### ErrorBlock Summary Expanded Examples
#### ErrorBlock Full Collapsed Examples
#### ErrorBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  [HTTP 429 rate_limit_error]
```

---

### ProxyErrorBlock — `None` (always visible)

An error originating from the cc-dump proxy itself (connection failures, parse errors, timeouts). Style: `bold {error}`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#proxyerrorblock-hidden-examples) |
| SC | `_render_proxy_error` | Proxy error message | [examples](#proxyerrorblock-summary-collapsed-examples) |
| SE | `_render_proxy_error` | Proxy error message | [examples](#proxyerrorblock-summary-expanded-examples) |
| FC | `_render_proxy_error` | Proxy error message | [examples](#proxyerrorblock-full-collapsed-examples) |
| FE | `_render_proxy_error` | Proxy error message | [examples](#proxyerrorblock-full-expanded-examples) |

#### ProxyErrorBlock Hidden Examples
No output produced.

#### ProxyErrorBlock Summary Collapsed Examples
#### ProxyErrorBlock Summary Expanded Examples
#### ProxyErrorBlock Full Collapsed Examples
#### ProxyErrorBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  [PROXY ERROR: Connection refused]
```

---

### UnknownTypeBlock — `None` (always visible)

A content block with an unrecognized type field from the API. Rendered as a fallback so no data is silently dropped. Style: `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#unknowntypeblock-hidden-examples) |
| SC | `_render_unknown_type` | Block type label | [examples](#unknowntypeblock-summary-collapsed-examples) |
| SE | `_render_unknown_type` | Block type label | [examples](#unknowntypeblock-summary-expanded-examples) |
| FC | `_render_unknown_type` | Block type label | [examples](#unknowntypeblock-full-collapsed-examples) |
| FE | `_render_unknown_type` | Block type label | [examples](#unknowntypeblock-full-expanded-examples) |

#### UnknownTypeBlock Hidden Examples
No output produced.

#### UnknownTypeBlock Summary Collapsed Examples
#### UnknownTypeBlock Summary Expanded Examples
#### UnknownTypeBlock Full Collapsed Examples
#### UnknownTypeBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
  [content_block_of_unknown_type]
```

---

## Hierarchical Containers

Section headers in the nested block structure. These are container labels — always single-line.

### MessageBlock — `None` (uses `block.category`: USER or ASSISTANT)

Container header for a message in the conversation array. Replaces RoleBlock in the hierarchical structure. Shows role, message index, and timestamp. Role uses `ROLE_STYLES`, timestamp is `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#messageblock-hidden-examples) |
| SC | `_render_message_block` | Role + index + timestamp | [examples](#messageblock-summary-collapsed-examples) |
| SE | `_render_message_block` | Role + index + timestamp | [examples](#messageblock-summary-expanded-examples) |
| FC | `_render_message_block` | Role + index + timestamp | [examples](#messageblock-full-collapsed-examples) |
| FE | `_render_message_block` | Role + index + timestamp | [examples](#messageblock-full-expanded-examples) |

#### MessageBlock Hidden Examples
No output produced.

#### MessageBlock Summary Collapsed Examples
#### MessageBlock Summary Expanded Examples
#### MessageBlock Full Collapsed Examples
#### MessageBlock Full Expanded Examples

All visible states produce identical output (1 line):

```
USER [0]  14:30:00
ASSISTANT [1]  14:30:05
```

---

### MetadataSection — `METADATA`

Container header for the request metadata group. Style: `bold dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#metadatasection-hidden-examples) |
| SC | `_render_metadata_section` | "METADATA" label | [examples](#metadatasection-summary-collapsed-examples) |
| SE | `_render_metadata_section` | "METADATA" label | [examples](#metadatasection-summary-expanded-examples) |
| FC | `_render_metadata_section` | "METADATA" label | [examples](#metadatasection-full-collapsed-examples) |
| FE | `_render_metadata_section` | "METADATA" label | [examples](#metadatasection-full-expanded-examples) |

#### MetadataSection Hidden Examples
No output produced.

#### MetadataSection Summary Collapsed Examples
#### MetadataSection Summary Expanded Examples
#### MetadataSection Full Collapsed Examples
#### MetadataSection Full Expanded Examples

All visible states: `METADATA`

---

### SystemSection — `SYSTEM`

Container header for the system prompt group. Style: `bold dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#systemsection-hidden-examples) |
| SC | `_render_system_section` | "SYSTEM" label | [examples](#systemsection-summary-collapsed-examples) |
| SE | `_render_system_section` | "SYSTEM" label | [examples](#systemsection-summary-expanded-examples) |
| FC | `_render_system_section` | "SYSTEM" label | [examples](#systemsection-full-collapsed-examples) |
| FE | `_render_system_section` | "SYSTEM" label | [examples](#systemsection-full-expanded-examples) |

#### SystemSection Hidden Examples
No output produced.

#### SystemSection Summary Collapsed Examples
#### SystemSection Summary Expanded Examples
#### SystemSection Full Collapsed Examples
#### SystemSection Full Expanded Examples

All visible states: `SYSTEM`

---

### ToolDefsSection — `TOOLS`

Container header for the tool definitions group. Shows count and total token estimate. Count is `bold dim`, tokens are `dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#tooldefssection-hidden-examples) |
| SC | `_render_tool_defs_section` | Tool count + tokens | [examples](#tooldefssection-summary-collapsed-examples) |
| SE | `_render_tool_defs_section` | Tool count + tokens | [examples](#tooldefssection-summary-expanded-examples) |
| FC | `_render_tool_defs_section` | Tool count + tokens | [examples](#tooldefssection-full-collapsed-examples) |
| FE | `_render_tool_defs_section` | Tool count + tokens | [examples](#tooldefssection-full-expanded-examples) |

#### ToolDefsSection Hidden Examples
No output produced.

#### ToolDefsSection Summary Collapsed Examples
#### ToolDefsSection Summary Expanded Examples
#### ToolDefsSection Full Collapsed Examples
#### ToolDefsSection Full Expanded Examples

All visible states produce identical output (1 line):

```
42 tools / 15.2k tokens
```

---

### ResponseMetadataSection — `METADATA`

Container header for the response metadata group. Style: `bold dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#responsemetadatasection-hidden-examples) |
| SC | `_render_response_metadata_section` | "RESPONSE METADATA" label | [examples](#responsemetadatasection-summary-collapsed-examples) |
| SE | `_render_response_metadata_section` | "RESPONSE METADATA" label | [examples](#responsemetadatasection-summary-expanded-examples) |
| FC | `_render_response_metadata_section` | "RESPONSE METADATA" label | [examples](#responsemetadatasection-full-collapsed-examples) |
| FE | `_render_response_metadata_section` | "RESPONSE METADATA" label | [examples](#responsemetadatasection-full-expanded-examples) |

#### ResponseMetadataSection Hidden Examples
No output produced.

#### ResponseMetadataSection Summary Collapsed Examples
#### ResponseMetadataSection Summary Expanded Examples
#### ResponseMetadataSection Full Collapsed Examples
#### ResponseMetadataSection Full Expanded Examples

All visible states: `RESPONSE METADATA`

---

### ResponseMessageBlock — `None` (context-dependent, ASSISTANT)

Container header for the response message. Style: `bold dim`.

| VisState | Renderer | Description | Examples |
|----------|----------|-------------|----------|
| Hidden | — | Not rendered | [examples](#responsemessageblock-hidden-examples) |
| SC | `_render_response_message_block` | "ASSISTANT" label | [examples](#responsemessageblock-summary-collapsed-examples) |
| SE | `_render_response_message_block` | "ASSISTANT" label | [examples](#responsemessageblock-summary-expanded-examples) |
| FC | `_render_response_message_block` | "ASSISTANT" label | [examples](#responsemessageblock-full-collapsed-examples) |
| FE | `_render_response_message_block` | "ASSISTANT" label | [examples](#responsemessageblock-full-expanded-examples) |

#### ResponseMessageBlock Hidden Examples
No output produced.

#### ResponseMessageBlock Summary Collapsed Examples
#### ResponseMessageBlock Summary Expanded Examples
#### ResponseMessageBlock Full Collapsed Examples
#### ResponseMessageBlock Full Expanded Examples

All visible states: `ASSISTANT`

---

## Category Index

| Category | Block Types |
|----------|-------------|
| `METADATA` | SeparatorBlock, HeaderBlock, HttpHeadersBlock, MetadataBlock, NewSessionBlock, TurnBudgetBlock, StreamInfoBlock, StopReasonBlock, MetadataSection, ResponseMetadataSection |
| `SYSTEM` | SystemLabelBlock, TrackedContentBlock, SystemSection |
| `TOOLS` | ToolDefinitionsBlock, ToolUseBlock, ToolResultBlock, ToolUseSummaryBlock, StreamToolUseBlock, ToolDefsSection, ToolDefBlock, SkillDefChild, AgentDefChild |
| `THINKING` | ThinkingBlock |
| `None` (uses `block.category`) | RoleBlock, TextContentBlock, TextDeltaBlock, ImageBlock, ConfigContentBlock, HookOutputBlock, MessageBlock, ResponseMessageBlock |
| `None` (always visible) | ErrorBlock, ProxyErrorBlock, NewlineBlock, UnknownTypeBlock |
