# Quick Reference Card

## Visual Examples at Each Level

### Example: System Prompts (s key)

#### Level 1: EXISTENCE `·`
```
▐ [sp-1] CHANGED (100→245 chars):
▐ [sp-2] UNCHANGED (512 chars)
```
**What you see:** Just the tag, status, and size for each tracked content item. Diffs hidden.

---

#### Level 2: SUMMARY `◐` (collapsed)
```
▶ ▐ [sp-1] CHANGED (100→245 chars):
    @@ -1,5 +1,8 @@
    + You are Claude Code
    ··· 8 more lines

▐ [sp-2] UNCHANGED (512 chars)
```
**What you see:** First 3 lines of diff for changed items. Click `▶` to expand to 12 lines.

---

#### Level 2: SUMMARY `◐` (expanded)
```
▼ ▐ [sp-1] CHANGED (100→245 chars):
    @@ -1,5 +1,8 @@
    + You are Claude Code
    + You help users with software
    + engineering tasks
    - Old instruction removed
    @@ -10,3 +13,6 @@
    + More changes here
    ··· 2 more lines

▐ [sp-2] UNCHANGED (512 chars)
```
**What you see:** Up to 12 lines of diff. Click `▼` to collapse back to 3 lines.

---

#### Level 3: FULL `●`
```
▼ ▐ [sp-1] CHANGED (100→245 chars):
    @@ -1,5 +1,8 @@
    + You are Claude Code
    + You help users with software
    + engineering tasks
    - Old instruction removed
    @@ -10,3 +13,6 @@
    + More changes here
    + Additional context
    [complete diff visible - 15 lines total]

▐ [sp-2] UNCHANGED:
    You are Claude Code, Anthropic's official CLI.
    You are an interactive agent that helps users
    with software engineering tasks...
    [full content - 512 chars / 42 lines]
```
**What you see:** Complete diff and full content for all tracked items. Click `▼` on long items to collapse to 5-line preview.

---

## Level Progression Chart

```
                    EXISTENCE          SUMMARY            FULL
                        ·                 ◐                ●
                      (1 line)         (3-12 lines)    (5-∞ lines)

Headers (h)        Turn structure    Basic headers    All HTTP headers
Tools (t)          "used 3 tools"    Tool counts      Full use/results
System (s)         Tag + status      First lines      Complete diffs
User (u)           First line        3-12 lines       Full message
Assistant (a)      First line        3-12 lines       Full message
Metadata (m)       One-liner         Breakdown        All fields
Budget (e)         Total tokens      Category split   Full accounting
```

## Default Configuration

When cc-dump starts:
```
h · headers      EXISTENCE  — clean turn structure
u ● user         FULL       — see all user input
a ● assistant    FULL       — see all responses
t ◐ tools        SUMMARY    — compact tool view
s ◐ system       SUMMARY    — system prompts with preview
m · metadata     EXISTENCE  — one-line summaries
e · budget       EXISTENCE  — token total only
```

**Result:** A clean conversation view with tool/system context available but not overwhelming.

## Common Workflows

### "I want to see EVERYTHING"
```bash
# Press each key 3 times (or until you see ● in footer):
h h h    # headers to FULL
t t      # tools to FULL (already at SUMMARY)
s s      # system to FULL
m m m    # metadata to FULL
e e e    # budget to FULL
```

### "Hide ALL the noise"
```bash
# Press each key until you see · in footer:
h        # headers already at EXISTENCE
t t      # tools to EXISTENCE
s s      # system to EXISTENCE
m        # metadata already at EXISTENCE
e        # budget already at EXISTENCE
```
Result: Ultra-compact view, just user/assistant messages.

### "Debug this tool call"
```bash
t        # Press once or twice until tools show FULL (●)
         # Individual tool blocks appear
         # Click ▶ on long result to expand
         # Click ▼ to collapse when done
```

### "What changed in the system prompt?"
```bash
s        # Press once to SUMMARY (◐)
         # See first lines of diff
         # Click ▶ on the changed item to see more
s        # Press again to FULL (●)
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

The footer shows current level for each category:

```
h·  t◐  s◐  m·  e·  u●  a●
│   │   │   │   │   │   └─ assistant: FULL
│   │   │   │   │   └───── user: FULL
│   │   │   │   └───────── budget: EXISTENCE
│   │   │   └───────────── metadata: EXISTENCE
│   │   └───────────────── system: SUMMARY
│   └───────────────────── tools: SUMMARY
└───────────────────────── headers: EXISTENCE
```

Active categories (level > EXISTENCE) have colored backgrounds matching their indicator bars.

## Technical Notes

### Line Limits

| Level | Collapsed | Expanded |
|-------|-----------|----------|
| EXISTENCE | 0 (hidden) | 1 (title only) |
| SUMMARY | 3 lines | 12 lines |
| FULL | 5 lines | unlimited |

### Category Assignment

- **Fixed:** Most blocks have a fixed category (e.g., `SeparatorBlock` → HEADERS)
- **Dynamic:** `TextContentBlock`, `RoleBlock`, `ImageBlock` get category set during formatting based on context (USER, ASSISTANT, or SYSTEM)

### Tool Summarization

At SUMMARY or EXISTENCE, consecutive tool use/result blocks are automatically combined into a single summary line:
```
[used 3 tools: Read 2x, Bash 1x]
```

At FULL, individual blocks are shown.

### State Persistence

- **Level changes:** Cycling a category level clears all per-block expansion overrides for that category
- **Click expansion:** Creates per-block overrides that persist until you cycle the level
- **Session:** Follow mode and scroll position persist across hot-reloads
