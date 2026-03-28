# Search

**Status:** draft

## Why Search Exists

Claude Code conversations are long, layered, and fast-moving. A single session can produce dozens of turns containing system prompts, tool calls, assistant responses, and metadata. When a user needs to find a specific tool invocation, a particular phrase in a system prompt diff, or a token count from earlier in the session, scrolling is impractical. Search gives the user vim-style `/` full-text search across all visible and hidden conversation content, with incremental feedback and match-by-match navigation.

## State Machine

Search has three phases, modeled as `SearchPhase`:

```
INACTIVE ──/──> EDITING ──Enter──> NAVIGATING
    ^              │                    │
    │              │ Esc (stay)         │ Esc (stay)
    │              │ q   (restore)      │ q   (restore)
    └──────────────┴────────────────────┘
```

- **INACTIVE:** No search bar visible. Normal key bindings active.
- **EDITING:** Search bar visible at bottom. All keystrokes go to the query editor. Incremental search runs with 150ms debounce (when incremental mode is enabled).
- **NAVIGATING:** Search bar visible. Query is locked. Navigation keys (`n`/`N`/Tab/etc.) cycle through matches. Other keys fall through to normal keymap.

The app's `_input_mode` property derives from the current phase: `INACTIVE` maps to `InputMode.NORMAL`, `EDITING` to `InputMode.SEARCH_EDIT`, `NAVIGATING` to `InputMode.SEARCH_NAV`.

## Invoking Search

Press `/` in normal mode. This transitions to EDITING phase and:

1. Clears any previous query and matches.
2. Saves current visibility filter state for all categories (so filters can be restored on cancel).
3. Saves current scroll position (for restore-on-cancel).
4. Shows the SearchBar widget (docked at bottom, up to 6 lines).

## The Search Bar

A 4-line display when active:

1. **Query line:** `/ <query>` with cursor (block cursor in editing mode, no cursor in navigating mode), plus match summary `[3/17]` or `[no matches]` or `[invalid pattern]`.
2. **Mode line:** Shows active mode flags with `Toggle: ` prefix: `Toggle: i` (case-insensitive), `w` (word boundary), `.*` (regex), `inc` (incremental).
3. **Toggle help:** `Alt+c =case  Alt+w =word  Alt+r =regex  Alt+i =incr`
4. **Navigation help:** Context-sensitive key hints (different for EDITING vs NAVIGATING).

The SearchBar is a Textual `Static` widget, not an `Input`. All key handling is centralized in the app's `on_key` dispatcher, not in the widget.

## What Is Searchable

Every block type in the FormattedBlock IR has a text extraction function registered in the `_TEXT_EXTRACTORS` dispatch table. This includes:

| Block Type | Searchable Text |
|---|---|
| `TextContentBlock` | Full content text |
| `TextDeltaBlock` | Content text |
| `ThinkingBlock` | Full thinking content |
| `ToolUseBlock` | Tool name + detail |
| `ToolResultBlock` | Tool name + detail |
| `ToolUseSummaryBlock` | Tool names with counts (e.g., `Read 2x Bash 1x`) |
| `ToolDefBlock` | Tool name + description |
| `HeaderBlock` | Label + timestamp |
| `HttpHeadersBlock` | All header key-value pairs joined |
| `MetadataBlock` | Model + max_tokens |
| `TurnBudgetBlock` | Context token estimate |
| `ResponseUsageBlock` | Input/output token counts |
| `ErrorBlock` | HTTP code + reason |
| `StreamInfoBlock` | Model name |
| `StopReasonBlock` | Stop reason |
| `ConfigContentBlock` | Content |
| `HookOutputBlock` | Content |
| `SkillDefChild` | Name + description |
| `AgentDefChild` | Name + description |
| `StreamToolUseBlock` | Tool name + detail |
| `ProxyErrorBlock` | Error message |
| `ImageBlock` | `"image: {media_type}"` |
| `UnknownTypeBlock` | Type label |
| `MessageBlock` | `"{role} {msg_index}"` (container — children searched recursively) |
| `SystemSection` | `"SYSTEM"` (container — children searched recursively) |

Blocks that produce empty strings (`SeparatorBlock`, `NewlineBlock`) are effectively unsearchable.

**Container children are searchable.** The search walks container blocks recursively (depth-first, children before parent), so content nested inside `MessageBlock`, `SystemSection`, `ToolDefsSection`, etc. is found. `ToolDefsSection` is a notable searchable container whose children include `ToolDefBlock`, `SkillDefChild`, and `AgentDefChild`. Child matches use the parent container's hierarchical index for block positioning but store the actual child block object for identity-based lookup.

**Streaming turns are skipped.** Only completed turns (`is_streaming == False`) are searched.

**Search order:** Turns are iterated most-recent-first (bottom-up). Within each turn, blocks are iterated bottom-up. Within each block, matches are reversed. This means pressing `n` (next) moves from the most recent match toward older content.

## Search Modes

Four independently togglable flags (`SearchMode` IntFlag):

| Mode | Flag | Default | Toggle Key | Effect |
|---|---|---|---|---|
| Case-insensitive | `CASE_INSENSITIVE` | On | `Alt+c` | Pattern compiled with `re.IGNORECASE` |
| Word boundary | `WORD_BOUNDARY` | Off | `Alt+w` | Pattern wrapped in `\b...\b` |
| Regex | `REGEX` | Off | `Alt+r` | Query used as raw regex (not escaped) |
| Incremental | `INCREMENTAL` | Off | `Alt+i` | Search runs on every keystroke (150ms debounce) |

When regex mode is off, the query is `re.escape()`-d for literal matching. An invalid regex pattern shows `[invalid pattern]` in the search bar.

## Editing Keys

While in EDITING phase, all keystrokes are consumed by search. The following editing actions are supported:

| Key | Action |
|---|---|
| Printable characters | Insert at cursor |
| `Backspace`, `Ctrl+H` | Delete character before cursor |
| `Delete`, `Ctrl+D` | Delete character at cursor |
| `Left` / `Right` | Move cursor |
| `Home`, `Ctrl+A` | Move to start |
| `End`, `Ctrl+E` | Move to end |
| `Alt+B` / `Alt+F` | Move word left / right |
| `Ctrl+W`, `Alt+Backspace` | Delete previous word |
| `Ctrl+U` | Kill to start of line |
| `Ctrl+K` | Kill to end of line |
| `Enter` | Commit search, enter NAVIGATING |
| `Escape` | Exit search, keep current scroll position |
| `q` | Inserts literal `q` (printable character). The `q`-to-restore-position behavior is only available in NAVIGATING phase. |

## Committing Search (Enter)

Pressing `Enter` in EDITING phase:

1. Cancels any pending incremental debounce timer.
2. Runs a final `run_search()` to compile the pattern and find all matches.
3. Sets `current_index = 0` (most recent match).
4. Transitions to NAVIGATING phase.
5. Calls `navigate_to_current()` to reveal and scroll to the first match.

## Navigation Keys (NAVIGATING Phase)

| Key | Action |
|---|---|
| `n`, `Enter`, `Ctrl+N`, `Tab` | Next match (wraps around) |
| `N`, `Ctrl+P`, `Shift+Tab` | Previous match (wraps around) |
| `/` | Re-enter EDITING (cursor at end of query) |
| `Escape` | Exit search, keep current scroll position |
| `q` | Exit search, restore original scroll position |

Keys not listed above fall through to the normal keymap, so vim navigation (`j`/`k`/`g`/`G` etc.) works while in NAVIGATING phase.

Navigation wraps: after the last match, `n` returns to the first.

## Exiting Search

Two exit modes, available in both EDITING and NAVIGATING phases:

- **Escape (keep position):** Captures current scroll anchor, then exits. The viewport stays where the user navigated to.
- **q (restore position):** Exits, then restores the scroll position saved when search was started.

Both exit modes:
1. Restore saved visibility filter levels (batched store update).
2. Reset query, matches, and current index to empty/zero.
3. Cancel any pending debounce timer.
4. Clear search highlight overlay via `clear_search_reveal()` (the public API for clearing search context and reveal state).
5. Re-render conversation without search context.

## Highlight Behavior

Search highlighting uses a **post-render strip overlay** applied at `render_line()` time. This is a pure visual decoration that does not affect strip geometry or cached turn data.

### How It Works

1. `_apply_search_to_strip()` runs on every visible strip during `render_line()`.
2. It extracts plain text from the strip's segments and runs the search pattern against it.
3. For each regex match span in the line, it applies a background color style via `Segment.divide()`.

### Two Highlight Tiers

- **All matches:** Dim background (`search_all_bg`, derived from theme surface color). Applied to every match span across all visible strips.
- **Current match:** Bright highlight (`search_current_style`, bold + accent color on contrasting background). Applied to match spans in strips belonging to the current match's block (determined by block identity, `current.block is block`).

The current-match highlight is block-scoped, not character-offset-scoped. All occurrences of the pattern within the current match's block get the bright highlight.

### Theme Integration

Highlight colors are derived from the active theme via `ThemeColors`:
- `search_all_bg` = theme surface color
- `search_current_style` = bold, black-on-accent (dark theme) or white-on-accent (light theme)
- Search bar uses `search_prompt_style` (bold primary), `search_active_style` (bold success), `search_error_style` (bold error), `search_keys_style` (bold warning)

## Reveal Behavior

When navigating to a match, the system ensures the matched block is visible even if its category is currently hidden or collapsed:

1. **Visibility override:** `ViewOverrides.set_search_reveal()` sets `vis_override = ALWAYS_VISIBLE` on the matched block. This overrides category-level visibility so the block renders even at EXISTENCE level.
2. **Region expansion:** If the match is inside a content region (determined by segmentation), the region's `expanded` override is set to `True` so the collapsed region expands to show the match.
3. **Scroll positioning:** The viewport scrolls to center the match. The exact strip line containing the match text is found by scanning the block's strips for the pattern, then `_scroll_to_line()` centers it vertically.
4. **Follow mode disabled:** Navigation always deactivates follow mode (auto-scroll).

Only one block + region can be revealed at a time. Navigating to a new match clears the previous reveal before setting the new one.

## Text Cache

Searchable text extraction is cached in a bounded LRU (`SearchTextCache`, max 20,000 entries). Entries are keyed by `(block_id_str, id(block))` and associated with an owner (turn identity). When turns are pruned, `invalidate_missing_owners()` evicts stale entries. The cache survives across searches within a session but is rebuilt after hot-reload.

## Hot-Reload Survival

Search identity state (phase, query, modes, cursor position, current index) is backed by a SnarfX view store and survives hot-reload via `reconcile()`. Transient state (matches list, debounce timer, text cache) is rebuilt by `run_search()` after reload.

## Contracts

- **Search is full-text, not structural.** You cannot search by block type, category, or turn role. The query matches against extracted plain text only.
- **Matches are ordered most-recent-first.** `n` moves toward older content, `N` toward newer.
- **Highlighting is a pure overlay.** It does not mutate cached strips, does not change block geometry, and is stripped on exit.
- **Reveal is temporary.** Visibility overrides set during search are cleared on exit. Saved filter state is restored.
- **One active reveal at a time.** Navigating to a new match clears the previous reveal.
- **Streaming turns are invisible to search.** Only completed turns are indexed.
