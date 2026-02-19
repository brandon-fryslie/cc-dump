# Block Hierarchy Restructuring: Visual Examples

## The API Data (for reference)

A single API turn: Claude Code sends a request, gets a streaming response.

**Request body** (simplified):
```json
{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 16384,
  "stream": true,
  "system": [{"type": "text", "text": "You are Claude Code, an AI assistant..."}],
  "tools": [
    {"name": "Read", "description": "Read files", "input_schema": {...}},
    {"name": "Bash", "description": "Run commands", "input_schema": {...}},
    {"name": "Edit", "description": "Edit files", "input_schema": {...}}
  ],
  "messages": [
    {"role": "user", "content": [
      {"type": "text", "text": "Fix the SSO login bug in auth.py"}
    ]},
    {"role": "assistant", "content": [
      {"type": "thinking", "thinking": "I need to look at auth.py to understand the SSO flow..."},
      {"type": "text", "text": "I'll examine the auth module to find the SSO issue."},
      {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "src/auth.py"}}
    ]},
    {"role": "user", "content": [
      {"type": "tool_result", "tool_use_id": "tu_1", "content": "def validate_sso_token(token):\n    ...142 lines..."}
    ]},
    {"role": "assistant", "content": [
      {"type": "thinking", "thinking": "The bug is in validate_sso_token - it doesn't handle expired tokens..."},
      {"type": "text", "text": "Found it. The `validate_sso_token` function doesn't handle expired tokens."},
      {"type": "tool_use", "id": "tu_2", "name": "Edit", "input": {"file_path": "src/auth.py", "old_string": "...", "new_string": "..."}}
    ]},
    {"role": "user", "content": [
      {"type": "tool_result", "tool_use_id": "tu_2", "content": "OK"}
    ]}
  ]
}
```

**Response** (streaming SSE):
```
message_start     → model: claude-sonnet-4-20250514, usage: {input: 4521, cache_read: 3800}
content_block     → type: thinking, "Now I should verify the fix by running the test suite..."
content_block     → type: text, "Let me run the tests to verify the fix."
content_block     → type: tool_use, name: Bash, input: {command: "pytest tests/test_auth.py -v"}
message_delta     → stop_reason: tool_use, output_tokens: 89
```

---

## Current cc-dump Layout (BEFORE)

Everything is a flat stream of blocks. The gutter bar on the left shows category color.
`▌` = category-colored bar, arrows (▶▷▼▽) = expandable indicators.

### Default view (headers/metadata/budget hidden, tools at summary)

```
▌    3 tools / 2.1k tokens                      ◁ tools (collapsed summary)
▌  SYSTEM:                                       ◁ system
▌▷   system:0  REF (38 lines):                   ◁ system (tracked, collapsed to 4 lines)
▌    You are Claude Code, an AI assis…
▌    … 34 more lines
▌                                                 ◁ (newline)
▌  USER                                           ◁ user
▌    Fix the SSO login bug in auth.py             ◁ user
▌                                                 ◁ (newline)
▌  ASSISTANT                                      ◁ assistant
▌    I'll examine the auth module to find…        ◁ assistant (thinking block MISSING)
▌  [used 1 tool: Read 1x]                         ◁ tools (collapsed run)
▌                                                 ◁ (newline)
▌  USER                                           ◁ user ← misleading: this is a tool result
▌  [used 1 tool: Read 1x]                         ◁ tools (collapsed run... misattributed)
▌                                                 ◁ (newline)
▌  ASSISTANT                                      ◁ assistant
▌    Found it. The `validate_sso_token`…          ◁ assistant (thinking block MISSING)
▌  [used 1 tool: Edit 1x]                         ◁ tools (collapsed run)
▌                                                 ◁ (newline)
▌  USER                                           ◁ user ← again misleading
▌  [used 1 tool: Edit 1x]                         ◁ tools (collapsed run)
▌                                                 ◁ (newline)
▌  RESPONSE (14:23:07)                            ◁ headers (hidden by default)
▌    model: claude-sonnet-4-20250514              ◁ metadata
▌  Let me run the tests to verify the fix.        ◁ assistant (thinking block MISSING)
▌                                                 ◁ (newline)
▌    [tool_use] Bash                              ◁ tools
▌                                                 ◁ (newline)
▌    stop: tool_use                               ◁ metadata
```

### Everything visible (all 7 categories on, tools at full expanded)

```
▌                                                 ◁ (newline)
▌  ──────────────────────────────────────────     ◁ headers (separator)
▌   REQUEST #1  (14:23:05)                        ◁ headers
▌  ──────────────────────────────────────────     ◁ headers (separator)
▌    model: claude-sonnet-4-20250514 | max…       ◁ metadata
▌▼ Host: api.anthropic.com | Content-Type…        ◁ headers (http headers)
▌    Host: api.anthropic.com
▌    Content-Type: application/json
▌    …
▌▼ input: 4,521 | cache_read: 3,800 | …          ◁ budget
▌    system: 812 tokens
▌    tools: 2,100 tokens
▌    messages: 1,609 tokens
▌    …
▌▷   3 tools / 2.1k tokens                       ◁ tools (tool defs, collapsed)
▌  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄        ◁ headers (thin separator)
▌  SYSTEM:                                        ◁ system
▌▼   system:0  REF (38 lines):                    ◁ system (tracked content, full)
▌    You are Claude Code, an AI assistant
▌    made by Anthropic. You help with
▌    software engineering tasks…
▌    [38 lines of system prompt]
▌  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄        ◁ headers
▌                                                 ◁ (newline)
▌  USER                                           ◁ user (RoleBlock)
▌    Fix the SSO login bug in auth.py             ◁ user (TextContentBlock)
▌                                                 ◁ (newline)
▌  ASSISTANT                                      ◁ assistant (RoleBlock)
▌    I'll examine the auth module to find…        ◁ assistant (TextContentBlock)
▌▼ [Use: Read] src/auth.py (3 lines)              ◁ tools (ToolUseBlock, expanded)
▌    file_path: src/auth.py
▌    Read files from the local filesystem…
▌                                                 ◁ (newline)
▌  USER                                           ◁ user (RoleBlock)
▌▼ [Result: Read] src/auth.py (142 lines)         ◁ tools (ToolResultBlock, expanded)
▌    def validate_sso_token(token):
▌        """Validate an SSO token."""
▌        if not token:
▌            …
▌                                                 ◁ (newline)
▌  ASSISTANT                                      ◁ assistant (RoleBlock)
▌    Found it. The `validate_sso_token`…          ◁ assistant (TextContentBlock)
▌▼ [Use: Edit] src/auth.py (8 lines)              ◁ tools (ToolUseBlock, expanded)
▌    file_path: src/auth.py
▌    old_string: "…"
▌    new_string: "…"
▌                                                 ◁ (newline)
▌  USER                                           ◁ user (RoleBlock)
▌▼ [Result: Edit] ✓                               ◁ tools (ToolResultBlock)
▌                                                 ◁ (newline)
▌  ──────────────────────────────────────────     ◁ headers
▌   RESPONSE  (14:23:07)                          ◁ headers
▌  ──────────────────────────────────────────     ◁ headers
▌▼ 200 | content-type: text/event-stream…         ◁ headers (response http headers)
▌    model: claude-sonnet-4-20250514              ◁ metadata (StreamInfoBlock)
▌  Let me run the tests to verify the fix.        ◁ assistant (TextDeltaBlock)
▌                                                 ◁ (newline)
▌    [tool_use] Bash                              ◁ tools (StreamToolUseBlock)
▌                                                 ◁ (newline)
▌    stop: tool_use                               ◁ metadata (StopReasonBlock)
```

### Problems with current layout

1. **No structural hierarchy.** Everything flat. No way to tell which content blocks
   belong to which message.

2. **Thinking blocks missing entirely.** The `thinking` content blocks from the API
   are silently dropped or misparsed as text.

3. **No message-level operations.** Can't collapse message [1] independently from [3].
   Can only toggle entire categories globally.

4. **Tool result messages are confusing.** `USER` header + tool block gives no signal
   that this "user message" is machine-generated tool output, not human input.

5. **Cross-message tool collapsing is lossy.** `collapse_tool_runs()` merges tool blocks
   across message boundaries into synthetic summaries, erasing message structure.

6. **No summarization at container levels.** You can summarize individual blocks, but
   there's no summary for "what does this entire message contain?"

7. **7 separate categories for 3 concerns.** Headers, metadata, and budget are separate
   filter toggles but semantically all "request chrome."

---

## Proposed Hierarchical Layout (AFTER)

Categories: METADATA (combined), USER, ASSISTANT, TOOLS, SYSTEM, THINKING

### Default view (metadata hidden, tools at summary, thinking collapsed)

```
▌▷ claude-sonnet-4 | 16k | 4,521 in (84% cached) ◁ metadata (collapsed section summary)
▌▷ 3 tools / 2.1k tokens                          ◁ tools (tool defs section)
▌▷ SYSTEM: 1 block (38 lines) — REF               ◁ system (section summary)
▌                                                   ◁
▌▼ USER [0]                                        ◁ user (message container)
▌  │ Fix the SSO login bug in auth.py              ◁ user (text child)
▌                                                   ◁
▌▼ ASSISTANT [1]                                   ◁ assistant (message container)
▌  │▷ [thinking] (4 lines)                         ◁ thinking (collapsed)
▌  │ I'll examine the auth module to find…         ◁ assistant (text child)
▌  │ [Use: Read] src/auth.py                       ◁ tools (tool_use child, summary)
▌                                                   ◁
▌▶ USER [2]: result(Read, 142 lines)               ◁ user (collapsed — only tool results)
▌                                                   ◁
▌▼ ASSISTANT [3]                                   ◁ assistant
▌  │▷ [thinking] (6 lines)                         ◁ thinking (collapsed)
▌  │ Found it. The `validate_sso_token`…           ◁ assistant (text child)
▌  │ [Use: Edit] src/auth.py                       ◁ tools (tool_use child, summary)
▌                                                   ◁
▌▶ USER [4]: result(Edit ✓)                        ◁ user (collapsed — only tool results)
▌                                                   ◁
▌  ─── RESPONSE (14:23:07) ─────────────           ◁ metadata
▌▼ ASSISTANT                                       ◁ assistant (response message container)
▌  │▷ [thinking] (3 lines)                         ◁ thinking (collapsed)
▌  │ Let me run the tests to verify the fix.       ◁ assistant (text child)
▌  │ [tool_use] Bash                               ◁ tools (tool_use child)
▌  stop: tool_use                                   ◁ metadata
```

### Expanding message [2] (click the ▶ arrow)

```
▌▼ USER [2]                                        ◁ user (now expanded)
▌  │▼ [Result: Read] src/auth.py (142 lines)       ◁ tools (tool_result, expanded)
▌  │  def validate_sso_token(token):
▌  │      """Validate an SSO token."""
▌  │      if not token:
▌  │          raise ValueError("Token required")
▌  │      …138 more lines
```

### Expanding a thinking block

```
▌▼ ASSISTANT [1]                                   ◁ assistant
▌  │▼ [thinking]                                   ◁ thinking (now expanded)
▌  │  I need to look at auth.py to understand
▌  │  the SSO flow. The user says login fails
▌  │  for SSO users specifically, so the issue
▌  │  is likely in token validation…
▌  │ I'll examine the auth module to find…         ◁ assistant (text child)
▌  │ [Use: Read] src/auth.py                       ◁ tools (tool_use child)
```

### Expanding metadata section

```
▌▼ claude-sonnet-4 | 16k | 4,521 in (84% cached)  ◁ metadata (section now expanded)
▌  │ model: claude-sonnet-4-20250514               ◁ metadata
▌  │ max_tokens: 16384 | stream: true              ◁ metadata
▌  │▷ HTTP headers (6 fields)                      ◁ metadata (sub-section collapsed)
▌  │▼ Token budget                                 ◁ metadata (sub-section expanded)
▌  │    input: 4,521 | cache_read: 3,800
▌  │    system: 812 tokens
▌  │    tools: 2,100 tokens
▌  │    messages: 1,609 tokens
```

### Expanding tool definitions section

```
▌▼ 3 tools / 2.1k tokens                           ◁ tools (section expanded)
▌  │▷ Read (340 tokens)                             ◁ tools (tool def, collapsed)
▌  │▷ Bash (520 tokens)                             ◁ tools (tool def, collapsed)
▌  │▷ Edit (410 tokens)                             ◁ tools (tool def, collapsed)
```

Expanding an individual tool def:
```
▌  │▼ Read (340 tokens)                             ◁ tools (tool def, expanded)
▌  │    Read files from the local filesystem.
▌  │    Parameters:
▌  │      file_path: string (required)
▌  │      offset: number
▌  │      limit: number
```

### Everything visible (all categories, fully expanded)

```
▌   REQUEST #1  (14:23:05)                          ◁ metadata
▌▼ claude-sonnet-4 | 16k | 4,521 in (84% cached)   ◁ metadata (expanded)
▌  │ model: claude-sonnet-4-20250514
▌  │ max_tokens: 16384 | stream: true
▌  │▼ HTTP headers
▌  │    Host: api.anthropic.com
▌  │    Content-Type: application/json
▌  │    …
▌  │▼ Token budget
▌  │    input: 4,521 | cache_read: 3,800
▌  │    system: 812 tokens
▌  │    tools: 2,100 tokens
▌  │    messages: 1,609 tokens
▌▼ 3 tools / 2.1k tokens                            ◁ tools (expanded)
▌  │▼ Read (340 tokens)
▌  │    Read files from the local filesystem…
▌  │    Parameters: file_path, offset, limit
▌  │▼ Bash (520 tokens)
▌  │    Run shell commands…
▌  │    Parameters: command, timeout
▌  │▼ Edit (410 tokens)
▌  │    Edit files…
▌  │    Parameters: file_path, old_string, new_string
▌▼ SYSTEM: 1 block (38 lines) — REF                 ◁ system (expanded)
▌  │▼   system:0  REF (38 lines)
▌  │    You are Claude Code, an AI assistant
▌  │    made by Anthropic. You help with
▌  │    software engineering tasks…
▌  │    [full 38 lines]
▌                                                    ◁
▌▼ USER [0]                                          ◁ user
▌  │ Fix the SSO login bug in auth.py
▌                                                    ◁
▌▼ ASSISTANT [1]                                     ◁ assistant
▌  │▼ [thinking]                                     ◁ thinking (expanded)
▌  │  I need to look at auth.py to understand
▌  │  the SSO flow…
▌  │ I'll examine the auth module to find…           ◁ assistant (text)
▌  │▼ [Use: Read] src/auth.py (3 lines)              ◁ tools (tool_use, expanded)
▌  │    file_path: src/auth.py
▌  │    Read files from the local filesystem…
▌                                                    ◁
▌▼ USER [2]                                          ◁ user
▌  │▼ [Result: Read] src/auth.py (142 lines)         ◁ tools (tool_result, expanded)
▌  │    def validate_sso_token(token):
▌  │        """Validate an SSO token."""
▌  │        …
▌                                                    ◁
▌▼ ASSISTANT [3]                                     ◁ assistant
▌  │▼ [thinking]                                     ◁ thinking
▌  │  The bug is in validate_sso_token — it
▌  │  doesn't handle expired tokens…
▌  │ Found it. The `validate_sso_token`…             ◁ assistant (text)
▌  │▼ [Use: Edit] src/auth.py (8 lines)              ◁ tools (tool_use, expanded)
▌  │    file_path: src/auth.py
▌  │    old_string: "…"
▌  │    new_string: "…"
▌                                                    ◁
▌▼ USER [4]                                          ◁ user
▌  │▼ [Result: Edit] ✓                               ◁ tools (tool_result)
▌                                                    ◁
▌  ─── RESPONSE (14:23:07) ─────────────             ◁ metadata
▌▼ 200 | content-type: text/event-stream…            ◁ metadata (response HTTP)
▌    model: claude-sonnet-4-20250514                 ◁ metadata
▌▼ ASSISTANT                                         ◁ assistant (response container)
▌  │▼ [thinking]                                     ◁ thinking
▌  │  Now I should verify the fix by running
▌  │  the test suite…
▌  │ Let me run the tests to verify the fix.         ◁ assistant (text)
▌  │▼ [tool_use] Bash                                ◁ tools (tool_use, expanded)
▌  │    pytest tests/test_auth.py -v
▌  stop: tool_use                                    ◁ metadata
```

---

## Filtering Examples

### Hide tools (toggle TOOLS off)

Tool_use and tool_result children vanish. Messages containing only tools auto-summarize:

```
▌▷ claude-sonnet-4 | 16k | 4,521 in (84% cached)  ◁ metadata
▌▷ SYSTEM: 1 block (38 lines) — REF                ◁ system
▌                                                    ◁
▌▼ USER [0]                                         ◁ user
▌  │ Fix the SSO login bug in auth.py
▌                                                    ◁
▌▼ ASSISTANT [1]                                    ◁ assistant
▌  │▷ [thinking] (4 lines)                          ◁ thinking
▌  │ I'll examine the auth module to find…          ◁ assistant (text)
▌                                                    ◁
▌▶ USER [2]: (tools hidden)                         ◁ user (all children filtered)
▌                                                    ◁
▌▼ ASSISTANT [3]                                    ◁ assistant
▌  │▷ [thinking] (6 lines)                          ◁ thinking
▌  │ Found it. The `validate_sso_token`…            ◁ assistant (text)
▌                                                    ◁
▌▶ USER [4]: (tools hidden)                         ◁ user (all children filtered)
▌                                                    ◁
▌▼ ASSISTANT                                        ◁ assistant (response)
▌  │▷ [thinking] (3 lines)
▌  │ Let me run the tests to verify the fix.
```

Note: tool definitions section also hidden (it's TOOLS category).

### Hide tools AND thinking — just the conversation text

```
▌▷ claude-sonnet-4 | 16k | 4,521 in (84% cached)
▌▷ SYSTEM: 1 block (38 lines) — REF
▌                                                    ◁
▌▼ USER [0]
▌  │ Fix the SSO login bug in auth.py
▌                                                    ◁
▌▼ ASSISTANT [1]
▌  │ I'll examine the auth module to find…
▌                                                    ◁
▌▶ USER [2]: (all content hidden)
▌                                                    ◁
▌▼ ASSISTANT [3]
▌  │ Found it. The `validate_sso_token`…
▌                                                    ◁
▌▶ USER [4]: (all content hidden)
▌                                                    ◁
▌▼ ASSISTANT
▌  │ Let me run the tests to verify the fix.
```

---

## Key Differences: Before vs After

| Aspect | Before | After |
|---|---|---|
| Block structure | Flat list per turn | Tree: sections → messages → content blocks |
| Categories | 7 (headers, metadata, budget separate) | 5+1 (metadata combined, thinking added) |
| Message identity | Implicit (RoleBlock delimiter) | Explicit (MessageBlock container) |
| Thinking blocks | Not supported | First-class content type, own category |
| Summarization | Only at individual block level | At every container level |
| Tool result messages | "USER" header + tool block (confusing) | Auto-summarizes: `USER [2]: result(Read)` |
| Message-level collapse | Not possible | Click any message to collapse/expand |
| Tool collapsing | Synthetic ToolUseSummaryBlock | Natural: message summary + child summaries |
| Content nesting | All same visual depth | Indented within parent container |
| Filtering | Category hides globally | Category hides at any depth, containers adapt |
| Metadata | 3 separate toggles | Single combined METADATA toggle |
