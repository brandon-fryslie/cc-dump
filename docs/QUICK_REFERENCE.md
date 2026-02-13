# Quick Reference Card

## Keyboard Shortcuts

### Category Filters (Number Keys)

| Key | Category | Action |
|-----|----------|--------|
| `1` | User | Toggle visibility |
| `2` | Assistant | Toggle visibility |
| `3` | Tools | Toggle visibility |
| `4` | System | Toggle visibility |
| `5` | Budget | Toggle visibility |
| `6` | Metadata | Toggle visibility |
| `7` | Headers | Toggle visibility (hidden ↔ remembered level) |

| Key | Action | Description |
|-----|--------|-------------|
| `!`, `@`, `#`, etc. | Toggle detail | Switch between SUMMARY and FULL (level 2 ↔ 3) |
| `Ctrl+Shift+<number>` | Expand/collapse all | Toggle all blocks in category |
| Click | Expand/collapse block | Toggle individual block within current level |

**Examples:**
- `1` hides/shows user messages
- `!` (Shift+1) toggles user between SUMMARY and FULL
- `7` hides/shows headers

### Panels & Modes

| Key | Action |
|-----|--------|
| `8` | Toggle cost panel (economics) |
| `9` | Toggle timeline panel |
| `0` | Toggle follow mode (auto-scroll) |
| `*` | Toggle economics breakdown (aggregate ↔ per-model) |
| `Ctrl+L` | Toggle logs panel |
| `Ctrl+P` | Command palette |

### Vim-Style Navigation

| Key | Action |
|-----|--------|
| `g` | Go to top (disables follow mode) |
| `G` | Go to bottom (enables follow mode) |
| `j` | Scroll down one line |
| `k` | Scroll up one line |
| `h` | Scroll left one column |
| `l` | Scroll right one column |
| `Ctrl+D` | Scroll down half page |
| `Ctrl+U` | Scroll up half page |
| `Ctrl+F` | Scroll down full page |
| `Ctrl+B` | Scroll up full page |

## Visual Examples at Each Level

### Example: System Prompts (4 key)

#### Level 1: EXISTENCE `·` (fully hidden)
```
(No output - category completely hidden)
```
**What you see:** Nothing. Press `4` again to show at SUMMARY level.

---

#### Level 2: SUMMARY `◐` (collapsed)
```
▐ ▶ [sp-1] CHANGED (100→245 chars):
      @@ -1,5 +1,8 @@
      + You are Claude Code
      ··· 8 more lines

▐   [sp-2] UNCHANGED (512 chars)
```
**What you see:** First 3 lines of diff for changed items. Arrow (▶) appears after color bar for expandable blocks. Click arrow to expand to 12 lines.

---

#### Level 2: SUMMARY `◐` (expanded)
```
▐ ▼ [sp-1] CHANGED (100→245 chars):
      @@ -1,5 +1,8 @@
      + You are Claude Code
      + You help users with software
      + engineering tasks
      - Old instruction removed
      @@ -10,3 +13,6 @@
      + More changes here
      ··· 2 more lines

▐   [sp-2] UNCHANGED (512 chars)
```
**What you see:** Up to 12 lines of diff. Arrow (▼) indicates expanded state. Click arrow to collapse back to 3 lines.

---

#### Level 3: FULL `●`
```
▐ ▼ [sp-1] CHANGED (100→245 chars):
      @@ -1,5 +1,8 @@
      + You are Claude Code
      + You help users with software
      + engineering tasks
      - Old instruction removed
      @@ -10,3 +13,6 @@
      + More changes here
      + Additional context
      [complete diff visible - 15 lines total]

▐   [sp-2] UNCHANGED:
      You are Claude Code, Anthropic's official CLI.
      You are an interactive agent that helps users
      with software engineering tasks...
      [full content - 512 chars / 42 lines]
```
**What you see:** Complete diff and full content for all tracked items. Arrow (▼) on expandable blocks can be clicked to collapse to 5-line preview.

---

## Level Progression Chart

```
                    EXISTENCE          SUMMARY            FULL
                        ·                 ◐                ●
                      (hidden)         (3-12 lines)    (5-∞ lines)

User (1)           Hidden            3-12 lines       Full message
Assistant (2)      Hidden            3-12 lines       Full message
Tools (3)          Hidden            Tool counts      Full use/results
System (4)         Hidden            First lines      Complete diffs
Budget (5)         Hidden            Category split   Full accounting
Metadata (6)       Hidden            Breakdown        All fields
Headers (7)        Hidden            Basic headers    All HTTP headers
```

## Default Configuration

When cc-dump starts:
```
1 ● user         FULL       — see all user input
2 ● assistant    FULL       — see all responses
3 ◐ tools        SUMMARY    — compact tool view
4 ◐ system       SUMMARY    — system prompts with preview
5 · budget       EXISTENCE  — hidden
6 · metadata     EXISTENCE  — hidden
7 · headers      EXISTENCE  — hidden (clean view)
```

**Result:** A clean conversation view focused on user/assistant messages, with tool/system context available but not overwhelming.

## Common Workflows

### "I want to see EVERYTHING"
```bash
# Show all hidden categories:
5        # show budget (toggles to remembered SUMMARY)
6        # show metadata (toggles to remembered SUMMARY)
7        # show headers (toggles to remembered SUMMARY)

# Then upgrade detail levels to FULL:
#        # tools SUMMARY → FULL
$        # system SUMMARY → FULL
%        # budget SUMMARY → FULL
^        # metadata SUMMARY → FULL
&        # headers SUMMARY → FULL
```

### "Hide ALL the noise"
```bash
# Hide everything except user/assistant:
3        # hide tools (press until hidden)
4        # hide system (press until hidden)
# 5, 6, 7 already hidden at EXISTENCE
```
Result: Ultra-compact view, just user/assistant messages.

### "Debug this tool call"
```bash
3        # If hidden, press to show at SUMMARY
#        # Press Shift+3 to toggle to FULL (●)
         # Individual tool blocks appear
         # Click ▶ on long result to expand
         # Click ▼ to collapse when done
```

### "What changed in the system prompt?"
```bash
4        # Press to show at SUMMARY (◐) if hidden
         # See first lines of diff
         # Click ▶ on the changed item to see more
$        # Press Shift+4 to toggle to FULL (●)
         # Complete diff visible
```

## Click Behavior

Clicking a block **only works within the current level**:

| Current State | After Click | Effect |
|---------------|-------------|--------|
| `▶` collapsed | `▼` expanded | Show more lines (up to level's expanded limit) |
| `▼` expanded | `▶` collapsed | Show fewer lines (level's collapsed limit) |
| No arrow | No change | Block fits within current limit |

**Important:** Clicking does NOT change the level. Use keyboard keys to change levels.

## Footer Legend

The footer shows current level for each category with key number and icon:

```
1●user  2●assistant  3◐tools  4◐system  5·budget  6·metadata  7·headers
│       │            │        │         │         │            └─ headers: EXISTENCE
│       │            │        │         │         └─────────────  metadata: EXISTENCE
│       │            │        │         └───────────────────────  budget: EXISTENCE
│       │            │        └─────────────────────────────────  system: SUMMARY
│       │            └──────────────────────────────────────────  tools: SUMMARY
│       └───────────────────────────────────────────────────────  assistant: FULL
└───────────────────────────────────────────────────────────────  user: FULL
```

Active categories (level > EXISTENCE) have colored backgrounds matching their indicator bars.

## Technical Notes

### Line Limits

| Level | Collapsed | Expanded |
|-------|-----------|----------|
| EXISTENCE | 0 (hidden) | 0 (hidden) |
| SUMMARY | 3 lines | 12 lines |
| FULL | 5 lines | unlimited |

**Note:** EXISTENCE level is now fully hidden (0 lines). Use SUMMARY level for compact views with titles/summaries.

### Category Assignment

- **Fixed:** Most blocks have a fixed category (e.g., `SeparatorBlock` → HEADERS)
- **Dynamic:** `TextContentBlock`, `RoleBlock`, `ImageBlock` get category set during formatting based on context (USER, ASSISTANT, or SYSTEM)

### Tool Summarization

At SUMMARY level, consecutive tool use/result blocks are automatically combined into a single summary line:
```
▐   [used 3 tools: Read 2x, Bash 1x]
```

At EXISTENCE level, tools are completely hidden (no summary line).

At FULL level, individual blocks are shown with full details.

### State Persistence

- **Level changes:** Toggling visibility or detail level clears all per-block expansion overrides for that category
- **Click expansion:** Creates per-block overrides that persist until you change the level
- **Remembered detail:** When you hide a category (level 1), it remembers whether it was at SUMMARY (2) or FULL (3), so toggling visibility restores the previous detail level
- **Session:** Follow mode and scroll position persist across hot-reloads
