# Quick Reference Card

## Keyboard Shortcuts

### Category Filters (Number Keys)

| Key | Category | Default | Action |
|-----|----------|---------|--------|
| `1` | User | visible, full, expanded | Toggle visibility on/off |
| `2` | Assistant | visible, full, expanded | Toggle visibility on/off |
| `3` | Tools | visible, summary, collapsed | Toggle visibility on/off |
| `4` | System | visible, summary, collapsed | Toggle visibility on/off |
| `5` | Metadata | hidden | Toggle visibility on/off |
| `6` | Thinking | visible, summary, collapsed | Toggle visibility on/off |

### Detail and Analytics Toggles

| Key | Alternate | Category | Action |
|-----|-----------|----------|--------|
| `!` or `Q` | Shift+1 | User | Toggle detail (full on/off) |
| `@` or `W` | Shift+2 | Assistant | Toggle detail (full on/off) |
| `#` or `E` | Shift+3 | Tools | Toggle detail (full on/off) |
| `$` or `R` | Shift+4 | System | Toggle detail (full on/off) |
| `%` or `T` | Shift+5 | Metadata | Toggle detail (full on/off) |
| `^` or `Y` | Shift+6 | Thinking | Toggle detail (full on/off) |

| Key | Category | Action |
|-----|----------|--------|
| `q` | User | Toggle analytics/expanded |
| `w` | Assistant | Toggle analytics/expanded |
| `e` | Tools | Toggle analytics/expanded |
| `r` | System | Toggle analytics/expanded |
| `t` | Metadata | Toggle analytics/expanded |
| `y` | Thinking | Toggle analytics/expanded |

**Examples:**
- `1` hides/shows user messages
- `!` (Shift+1) or `Q` toggles user detail level (full on/off)
- `q` toggles user expanded/collapsed within current level

### Panels & Modes

| Key | Action |
|-----|--------|
| `.` | Cycle panel |
| `,` | Cycle panel mode (e.g., aggregate vs per-model) |
| `f` | Toggle follow mode (auto-scroll) |
| `i` | Toggle info panel |
| `?` | Toggle keys panel |
| `S` | Toggle settings panel |
| `C` | Toggle launch config panel |
| `D` | Toggle debug settings panel |
| `Ctrl+L` | Toggle logs panel |

### Search & Presets

| Key | Action |
|-----|--------|
| `/` | Enter search mode |
| `=` | Next filterset preset |
| `-` | Previous filterset preset |
| `Alt+N` | Jump to next special section |
| `Alt+P` | Jump to previous special section |

### Vim-Style Navigation

| Key | Action |
|-----|--------|
| `g` | Go to top |
| `G` | Go to bottom |
| `j` | Scroll down one line |
| `k` | Scroll up one line |
| `h` | Scroll left one column |
| `l` | Scroll right one column |

In search navigation mode (`/` then Enter), additional keys are available:

| Key | Action |
|-----|--------|
| `Ctrl+D` | Scroll down half page |
| `Ctrl+U` | Scroll up half page |
| `Ctrl+F` | Scroll down full page |
| `Ctrl+B` | Scroll up full page |
| `n` / `N` | Next / previous search match |

### Other

| Key | Action |
|-----|--------|
| `[` / `]` | Previous / next theme |
| `{` / `}` | Previous / next session |
| `c` | Launch tool (tmux) |
| `L` | Open tmux log tail |
| `Ctrl+C Ctrl+C` | Quit |

## Visibility Model

Each category has three independent boolean flags:

| Flag | Store key | Toggled by | Effect |
|------|-----------|------------|--------|
| **visible** | `vis:<name>` | Number key (1-6) | Show/hide the category entirely |
| **full** | `full:<name>` | Shift+number or QWERTY uppercase | Toggle between summary and full detail |
| **expanded** | `exp:<name>` | qwerty lowercase | Toggle expanded/collapsed within current detail level |

These combine into 5 states when cycling (used by filterset presets):

| State | visible | full | expanded | Description |
|-------|---------|------|----------|-------------|
| Hidden | false | false | false | Category not shown |
| Summary Collapsed | true | false | false | Compact view |
| Summary Expanded | true | false | true | Expanded compact view |
| Full Collapsed | true | true | false | Full detail, collapsed |
| Full Expanded | true | true | true | Full detail, expanded |

## Default Configuration

When cc-dump starts:
```
1  user         visible, full, expanded     -- see all user input
2  assistant    visible, full, expanded     -- see all responses
3  tools        visible, summary, collapsed -- compact tool view
4  system       visible, summary, collapsed -- system prompts with preview
5  metadata     hidden                      -- hidden by default
6  thinking     visible, summary, collapsed -- thinking blocks with preview
```

The default filterset is F1 "Conversation".

## Filterset Presets

Cycle through presets with `=` (next) and `-` (previous). Available slots:

| Slot | Name |
|------|------|
| F1 | Conversation |
| F2 | Overview |
| F4 | Tools |
| F5 | System |
| F6 | Cost |
| F7 | Full Debug |
| F8 | Assistant |
| F9 | Minimal |

Note: F3 is skipped in the cycle.

## Click Behavior

Clicking a block toggles its expansion **within the current level**:

| Current State | After Click | Effect |
|---------------|-------------|--------|
| Collapsed | Expanded | Show more lines |
| Expanded | Collapsed | Show fewer lines |
| No arrow | No change | Block fits within current limit |

**Important:** Clicking does NOT change the visibility or detail level. Use keyboard keys for that.

## Footer Legend

The footer shows current state for each category:

```
1-6 filters  qwerty analytics  QWERTY detail  . panel  , mode  f follow  ...
```

Active categories have colored backgrounds matching their indicator bars.

## Common Workflows

### "I want to see everything"
```
5        # show metadata (toggle visible)
Q W E R T Y   # toggle all to full detail
q w e r t y   # expand all categories
```

### "Hide the noise"
```
3        # hide tools
4        # hide system
6        # hide thinking
# 5 already hidden
```
Result: Just user/assistant messages.

### "Debug a tool call"
```
3        # show tools if hidden
E        # toggle tools to full detail
e        # expand tools
         # click individual blocks to expand/collapse
```

### "What changed in the system prompt?"
```
4        # show system if hidden
R        # toggle system to full detail
         # full diff now visible
```

## Technical Notes

### Category Assignment

- **Dynamic:** `TextContentBlock`, `RoleBlock`, `ImageBlock` get their category set during formatting based on context (USER, ASSISTANT, or SYSTEM)
- **Fixed:** Most other block types have a fixed category mapping

### Tool Summarization

When tools are visible but not at full detail, consecutive tool use/result blocks are automatically combined into a summary line:
```
[used 3 tools: Read 2x, Bash 1x]
```

At full detail, individual blocks are shown with complete content.

### State Persistence

- **Override clearing:** Toggling visibility or detail level resets per-block expansion overrides for that category
- **Follow mode** and scroll position persist across hot-reloads
