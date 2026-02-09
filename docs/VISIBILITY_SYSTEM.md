# 3-Level × 2-State Visibility System

## Overview

The visibility system provides fine-grained control over what content is displayed in the TUI. Each category of content (headers, tools, system, user, assistant, metadata, budget) can be cycled through **3 visibility levels**, and within each level, individual blocks can be toggled between **2 expansion states**.

**3 Levels × 2 States = 6 visual representations per block type**

## Core Concepts

### The Three Levels

| Level | Name | Purpose |
|-------|------|---------|
| **Level 1** | EXISTENCE | Minimal — just show that content exists (typically 1 line) |
| **Level 2** | SUMMARY | Mid-level — meaningful summary without full details (3-12 lines) |
| **Level 3** | FULL | Complete — all content visible (5 lines to unlimited) |

### The Two States (per level)

| State | Symbol | Purpose |
|-------|--------|---------|
| **Collapsed** | `▶` | Show truncated version within the current level |
| **Expanded** | `▼` | Show more content within the current level |

The expand/collapse arrows (`▶`/`▼`) only appear when a block has more content than the current line limit allows.

### Default States

When you cycle to a new level, blocks reset to these defaults:
- **EXISTENCE**: expanded (show title lines — otherwise nothing would be visible)
- **SUMMARY**: collapsed (show compact summaries, click to see more)
- **FULL**: expanded (show everything, click to collapse what you don't need)

## Keyboard Controls

### Category Cycling

Press a category key to cycle through: EXISTENCE → SUMMARY → FULL → EXISTENCE

| Key | Category | Default Level | Includes |
|-----|----------|---------------|----------|
| `h` | Headers | EXISTENCE | Separators, turn headers, HTTP headers |
| `u` | User | FULL | User messages and role labels |
| `a` | Assistant | FULL | Assistant messages and role labels |
| `t` | Tools | SUMMARY | Tool use/result blocks, tool summaries |
| `s` | System | SUMMARY | System prompts, tracked content, system labels |
| `m` | Metadata | EXISTENCE | Metadata blocks, stream info |
| `e` | Budget | EXISTENCE | Token budget blocks, cache information |

**Example:** Press `h` three times: EXISTENCE → SUMMARY → FULL → (back to) EXISTENCE

### Click to Expand/Collapse

Click on any block to toggle its expansion state **within the current level**:
- If collapsed (`▶`) → expand to show more lines
- If expanded (`▼`) → collapse to show fewer lines

**Only works if the block has more content than the current line limit.**

### Footer Display

The footer shows the current level for each category using icons:
- `·` = EXISTENCE (level 1)
- `◐` = SUMMARY (level 2)
- `●` = FULL (level 3)

Active categories (level > EXISTENCE) are highlighted with a colored background.

## Visual Examples

### Headers (h key)

**EXISTENCE** (default):
```
────────────────────────────────────────────────────────────────
REQUEST #1
────────────────────────────────────────────────────────────────
```
Just the separator and header line. HTTP headers hidden.

**SUMMARY**:
```
────────────────────────────────────────────────────────────────
REQUEST #1
────────────────────────────────────────────────────────────────
▶ HTTP Request Headers (7 headers)
```
Shows that headers exist with a count, collapsed by default. Click to expand.

**FULL**:
```
────────────────────────────────────────────────────────────────
REQUEST #1
────────────────────────────────────────────────────────────────
▼ HTTP Request Headers:
  Content-Type: application/json
  anthropic-version: 2023-06-01
  x-api-key: sk-ant-***
  ... (all headers)
```
All HTTP headers visible.

### Tools (t key)

**EXISTENCE**:
```
[used 3 tools: Read 2x, Bash 1x]
```
One-line summary showing which tools were used and how many times.

**SUMMARY** (default):
```
▶ [used 3 tools: Read 2x, Bash 1x]
```
Same as EXISTENCE but with expand arrow (clicking does nothing — it's already a summary).

**FULL**:
```
▼ [Use: Read] /Users/bmf/code/file.py
  [Result: Read] (5678 bytes)

▼ [Use: Read] /Users/bmf/code/other.py
  [Result: Read] (3456 bytes)
  ··· 40 more lines

▶ [Use: Bash] ls -la
  [Result: Bash] (234 bytes)
  total 48
  drwxr-xr-x  12 user  staff   384 Feb  8 10:30 .
  ··· 15 more lines
```
Individual tool use/result blocks. Click `▶` on a long result to expand it.

### System Prompts (s key)

**EXISTENCE**:
```
▐ [sp-1] CHANGED (100→245 chars):
```
Just shows the tag and status for each tracked content item.

**SUMMARY** (default):
```
▶ ▐ [sp-1] CHANGED (100→245 chars):
    @@ -1,5 +1,8 @@
    + added line 1
    ··· 8 more lines
```
First few lines of diff, collapsed. Click to see more.

**FULL**:
```
▼ ▐ [sp-1] CHANGED (100→245 chars):
    @@ -1,5 +1,8 @@
    + added line 1
    + added line 2
    - removed line
    @@ -10,3 +13,6 @@
    + more changes
    (full diff visible)
```
Complete diff visible. Click `▼` to collapse to 5-line preview.

### User/Assistant Messages (u/a keys)

**EXISTENCE**:
```
I'll help you with that. Let me...
```
First line only.

**SUMMARY**:
```
▶ I'll help you with that. Let me look at the
    formatting module to understand how it works
    and then make the necessary changes.
    ··· 40 more lines
```
First 3 lines (collapsed) or up to 12 lines (expanded).

**FULL** (default):
```
▼ I'll help you with that. Let me look at the
    formatting module to understand how it works
    and then make the necessary changes.

    First, I'll read the current implementation...

    [entire message visible]
```
Complete message. Long messages can be clicked to collapse to 5-line preview.

### Metadata/Budget (m/e keys)

**EXISTENCE** (default):
```
Model: claude-opus-4 | Tokens: 1024 | Stream: true | Tools: 3
```
One-line summary for metadata.

```
Context: 50.2K tokens (input) + 2.1K (cache-write) = 52.3K
```
One-line budget summary.

**SUMMARY**:
More detailed breakdown (3-12 lines depending on content).

**FULL**:
Complete token accounting, cache details, all metadata fields.

## Line Limits Reference

| Level | Collapsed Lines | Expanded Lines |
|-------|-----------------|----------------|
| EXISTENCE | 0 (hidden) | 1 (title) |
| SUMMARY | 3 | 12 |
| FULL | 5 | unlimited |

## Workflow Examples

### "I just want to see the conversation"
```
Default state:
- headers: EXISTENCE (minimal)
- user: FULL (see everything)
- assistant: FULL (see everything)
- tools: SUMMARY (compact view)
- system: SUMMARY (compact view)
- metadata: EXISTENCE (one line)
- budget: EXISTENCE (one line)
```
Result: Clean conversation view with tool/system context available but not overwhelming.

### "Show me everything"
Press `h`, `t`, `s`, `m`, `e` three times each (or twice if they're at SUMMARY):
```
All categories at FULL level:
- Every separator, header, and HTTP header visible
- All tool use/results in full detail
- Complete system prompts and diffs
- Full metadata and token accounting
```

### "Hide the noise"
Press keys to cycle to EXISTENCE:
```
- h → EXISTENCE: minimal turn structure
- t → EXISTENCE: one-line tool summary
- s → EXISTENCE: system prompt tags only
- m → EXISTENCE: one-line metadata
- e → EXISTENCE: one-line budget
```
Result: Ultra-compact view showing only the core conversation.

### "Debug this tool call"
1. Press `t` to cycle tools to FULL (if at SUMMARY or EXISTENCE)
2. Click on the specific tool result block with `▶` to expand it
3. Read the full output
4. Click `▼` to collapse when done

## Technical Details

### Block Category Assignment

Most blocks have a fixed category (e.g., `SeparatorBlock` → HEADERS), but some are context-dependent:
- `TextContentBlock` → category set during formatting (USER, ASSISTANT, or SYSTEM)
- `RoleBlock` → category set during formatting
- `ImageBlock` → category set during formatting

### Tool Summarization

When tools are at SUMMARY or EXISTENCE, consecutive tool use/result pairs are automatically collapsed into a single `ToolUseSummaryBlock` showing counts:
```
[used 3 tools: Read 2x, Bash 1x]
```

At FULL level, individual `ToolUseBlock` and `ToolResultBlock` instances are shown.

### Cache Display Timing

Budget blocks show cache information (cache hits, cache writes) only after the response completes. During streaming, only input/output token counts are shown.

### Persistent State

When you cycle a category level, all per-block expansion overrides for that category are cleared (reset to the level's default). Click-based expansion/collapse creates per-block overrides that persist until you cycle the level.

## Keyboard Reference Card

```
┌─ Visibility Controls ──────────────────────────────────────────┐
│                                                                 │
│  h     Headers       · → ◐ → ● → ·   (separators, turn headers)│
│  u     User          · → ◐ → ● → ·   (user messages)           │
│  a     Assistant     · → ◐ → ● → ·   (assistant messages)      │
│  t     Tools         · → ◐ → ● → ·   (tool use/results)        │
│  s     System        · → ◐ → ● → ·   (system prompts, content) │
│  m     Metadata      · → ◐ → ● → ·   (metadata, stream info)   │
│  e     Budget        · → ◐ → ● → ·   (token accounting)        │
│                                                                 │
│  click Block with ▶  Expand within current level               │
│  click Block with ▼  Collapse within current level             │
│                                                                 │
│  Icons:  · existence  ◐ summary  ● full                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Removed Features

The following navigation features were removed as part of this update:
- Turn selection (j/k keys)
- Tool turn jumping (n/N keys)
- Jump to first/last (g/G keys)
- Click to select turn

These were replaced with the simpler click-to-expand/collapse interaction model.
