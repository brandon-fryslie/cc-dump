# Visibility System

> Status: draft
> Last verified against: not yet

## Overview

A single Claude Code API request can produce dozens of blocks: HTTP headers, metadata,
system prompts, tool definitions, user messages, assistant responses, tool calls and
results, budget breakdowns, and thinking content. Showing everything at once is
overwhelming. A simple show/hide toggle is too coarse — users need to see that tools
*exist* without reading every result, or see system prompt *diffs* without the full
prompt text.

The visibility system solves this with **progressive disclosure across three axes**.
Each content category has an independent visibility state composed of three boolean
flags — visible, full, and expanded — producing five meaningful states from hidden
through fully expanded. Users control these with number keys (quick toggle), shifted
keys (detail toggle), letter keys (analytics toggle), footer chip clicks (5-state
cycling), and per-block click interactions. All per-block expansion overrides reset
when the category-level state changes, keeping the mental model simple: category
state is the baseline, block overrides are local adjustments within that baseline.

## Categories

Every block of content belongs to exactly one **category**. There are 6 categories:

| Category | Enum Value | Description |
|----------|-----------|-------------|
| USER | `"user"` | User messages and related content |
| ASSISTANT | `"assistant"` | Assistant responses |
| TOOLS | `"tools"` | Tool definitions, tool use, tool results, tool summaries |
| SYSTEM | `"system"` | System prompts and system-level content |
| METADATA | `"metadata"` | HTTP headers, turn budgets, stream info, stop reasons, usage, session separators |
| THINKING | `"thinking"` | Extended thinking / reasoning blocks |

### Category Assignment

A block's category is determined by a two-step resolution:

1. **Dynamic category** (`block.category` field): Set during formatting when the block's
   category depends on context. For example, a `TextContentBlock` is assigned USER or
   ASSISTANT depending on which role's message it appears in.
2. **Static mapping** (per block type): A lookup table maps block type names to categories.
   Used when `block.category` is `None`.

If both are `None`, the block is **always visible** — it has no category and is not subject
to visibility filtering. Examples: `ErrorBlock`, `ProxyErrorBlock`, `NewlineBlock`.

Static category assignments:

| Block Type | Category |
|-----------|----------|
| `SeparatorBlock` | METADATA |
| `HeaderBlock` | METADATA |
| `HttpHeadersBlock` | METADATA |
| `MetadataBlock` | METADATA |
| `NewSessionBlock` | METADATA |
| `TurnBudgetBlock` | METADATA |
| `StreamInfoBlock` | METADATA |
| `StopReasonBlock` | METADATA |
| `ResponseUsageBlock` | METADATA |
| `MetadataSection` | METADATA |
| `ResponseMetadataSection` | METADATA |
| `ToolUseBlock` | TOOLS |
| `ToolResultBlock` | TOOLS |
| `ToolUseSummaryBlock` | TOOLS |
| `StreamToolUseBlock` | TOOLS |
| `ToolDefsSection` | TOOLS |
| `ToolDefBlock` | TOOLS |
| `SkillDefChild` | TOOLS |
| `AgentDefChild` | TOOLS |
| `SystemSection` | SYSTEM |
| `ThinkingBlock` | THINKING |
| `TextContentBlock` | *dynamic* (USER, ASSISTANT, or SYSTEM) |
| `TextDeltaBlock` | *dynamic* |
| `ImageBlock` | *dynamic* |
| `MessageBlock` | *dynamic* (USER or ASSISTANT) |
| `ConfigContentBlock` | *none* (inherits from parent) |
| `HookOutputBlock` | *none* (inherits from parent) |
| `ErrorBlock` | *none* (always visible) |
| `ProxyErrorBlock` | *none* (always visible) |
| `NewlineBlock` | *none* (always visible) |
| `UnknownTypeBlock` | *none* (always visible) |

## VisState: The Visibility Representation

Visibility for a category is represented by `VisState`, a named tuple with three boolean fields:

```
VisState(visible: bool, full: bool, expanded: bool)
```

| Field | Meaning when `True` | Meaning when `False` |
|-------|---------------------|----------------------|
| `visible` | Category is shown | Category is hidden (0 lines) |
| `full` | Full detail level | Summary detail level |
| `expanded` | Expanded view | Collapsed view |

These three axes combine into 8 theoretical states. The 4 states where `visible=False`
all produce the same result (hidden, 0 lines), so there are **5 meaningful states**:

| # | State Name | VisState | Line Limit |
|---|-----------|----------|------------|
| 1 | Hidden | `(False, False, False)` | 0 |
| 2 | Summary Collapsed | `(True, False, False)` | 3 |
| 3 | Summary Expanded | `(True, False, True)` | 8 |
| 4 | Full Collapsed | `(True, True, False)` | 5 |
| 5 | Full Expanded | `(True, True, True)` | unlimited |

Two named constants:
- `HIDDEN = VisState(False, False, False)` — invisible
- `ALWAYS_VISIBLE = VisState(True, True, True)` — full expanded, used for uncategorized blocks and search reveal

### Truncation Limits

Each VisState maps to a maximum number of rendered lines:

| VisState | Max Lines |
|----------|-----------|
| Any `visible=False` | 0 |
| `(True, False, False)` — summary collapsed | 3 |
| `(True, False, True)` — summary expanded | 8 |
| `(True, True, False)` — full collapsed | 5 |
| `(True, True, True)` — full expanded | unlimited |

When a block's rendered output exceeds its truncation limit, the block is marked
**expandable**. Expandable blocks show a visual indicator (arrow) and respond to
click interactions. Blocks that fit within their limit are not expandable and show
no arrow.

## Default Configuration

At startup, each category has a default VisState:

| Key | Category | Default VisState | Effect |
|-----|----------|-----------------|--------|
| 1 | user | `(True, True, True)` | Full expanded — see all user input |
| 2 | assistant | `(True, True, True)` | Full expanded — see all responses |
| 3 | tools | `(True, False, False)` | Summary collapsed — compact tool view |
| 4 | system | `(True, False, False)` | Summary collapsed — system prompt previews |
| 5 | metadata | `(False, False, False)` | Hidden — clean view |
| 6 | thinking | `(True, False, False)` | Summary collapsed — thinking previews |

These defaults are defined in `FILTER_SPECS` in the filter registry and are the
canonical source for initial visibility state.

## Keyboard Controls

All keyboard input routes through a modal key dispatch system. Visibility keys are
available in NORMAL mode only (not during search editing).

### Number Keys: Visibility Toggle (`toggle_vis`)

Keys `1` through `6` toggle the `visible` flag for the corresponding category.

| Key | Category | Action |
|-----|----------|--------|
| `1` | user | Toggle `vis:user` |
| `2` | assistant | Toggle `vis:assistant` |
| `3` | tools | Toggle `vis:tools` |
| `4` | system | Toggle `vis:system` |
| `5` | metadata | Toggle `vis:metadata` |
| `6` | thinking | Toggle `vis:thinking` |

**Behavior:** Toggles only the `visible` flag. The `full` and `expanded` flags are
preserved, so when a category is made visible again it returns to its previous detail
level (remembered state).

**State transitions for `toggle_vis`:**
- Spec: `[("vis", None)]` — toggle the vis flag, touch nothing else.
- Example: tools at `(True, False, False)` → press `3` → `(False, False, False)` (hidden)
- Press `3` again → `(True, False, False)` (back to summary collapsed)

### Shifted Number Keys: Detail Toggle (`toggle_detail`)

Shifted number keys (`!`, `@`, `#`, `$`, `%`, `^`) toggle between summary and full
detail levels. Alternative bindings exist on shifted letter keys (`Q`, `W`, `E`, `R`, `T`, `Y`).

| Key | Alt Key | Category | Action |
|-----|---------|----------|--------|
| `!` | `Q` | user | Toggle `full:user` |
| `@` | `W` | assistant | Toggle `full:assistant` |
| `#` | `E` | tools | Toggle `full:tools` |
| `$` | `R` | system | Toggle `full:system` |
| `%` | `T` | metadata | Toggle `full:metadata` |
| `^` | `Y` | thinking | Toggle `full:thinking` |

**Behavior:** Forces `visible=True`, then toggles the `full` flag.

**State transitions for `toggle_detail`:**
- Spec: `[("vis", True), ("full", None)]` — force visible, toggle full.
- Example: tools hidden at `(False, False, False)` → press `#` → `(True, True, False)` (full collapsed)
- Press `#` again → `(True, False, False)` (summary collapsed)

### Letter Keys: Analytics Toggle (`toggle_analytics`)

Letter keys (`q`, `w`, `e`, `r`, `t`, `y`) toggle the `expanded` flag, used
for analytics/expansion detail.

| Key | Category | Action |
|-----|----------|--------|
| `q` | user | Toggle `exp:user` |
| `w` | assistant | Toggle `exp:assistant` |
| `e` | tools | Toggle `exp:tools` |
| `r` | system | Toggle `exp:system` |
| `t` | metadata | Toggle `exp:metadata` |
| `y` | thinking | Toggle `exp:thinking` |

**Behavior:** Forces `visible=True`, then toggles the `expanded` flag.

**State transitions for `toggle_analytics`:**
- Spec: `[("vis", True), ("exp", None)]` — force visible, toggle expanded.
- Example: tools at `(True, False, False)` → press `e` → `(True, False, True)` (summary expanded)
- Press `e` again → `(True, False, False)` (summary collapsed)

### Footer Chip Clicks: 5-State Cycling (`cycle_vis`)

Clicking a category chip in the footer cycles through all 5 visibility states in order:

```
Hidden → Summary Collapsed → Summary Expanded → Full Collapsed → Full Expanded → Hidden → ...
```

The cycle wraps around. If the current state is not found in the cycle (e.g., from an
unusual combination), cycling starts from Hidden.

### Override Clearing on State Change

Every keyboard toggle and chip cycle operation **clears all per-block expansion overrides**
for the affected category before applying the state change. This ensures the new category
state is the sole determinant of block visibility — there are no stale block-level
overrides leaking through from a previous state.

The active filterset indicator is also cleared (set to `None`) on any manual visibility
change, since the state no longer matches a named preset.

## Per-Block Expansion (Click Behavior)

Within a given category visibility state, individual blocks can be expanded or collapsed
by clicking. This is a **local adjustment** — it does not change the category state.

### Expandability

A block is **expandable** when its rendered output exceeds the truncation limit for
its current VisState. The rendering system sets the `expandable` flag on a block's
view state during rendering. Only expandable blocks respond to click interactions.

### Click Toggling

Clicking an expandable block toggles its `expanded` override between `True` and
`False`. The expanded override replaces the category-level expanded state for that
specific block only.

- Clicking a collapsed expandable block → sets `expanded=True` on its view state
- Clicking an expanded block → sets `expanded=False`
- Clicking a non-expandable block → no effect on expansion (stores click position
  for double-click text selection)

The block is re-rendered using the same category VisState but with the block's
`expanded` field overridden by the per-block value.

### Visual Indicators

- `▶` — expandable, currently collapsed (more content available)
- `▼` — expandable, currently expanded (can be collapsed)
- No arrow — block fits within its limit, not expandable

### Scope of Click Expansion

Click expansion operates **within the current level**. It changes how many lines of a
block are shown, but does not change whether the block is at summary or full detail.
For example, clicking a tool block at summary level expands it from 3 to 8 lines,
not to unlimited. This separation exists because if clicking jumped directly to full
expanded, there would be no medium-detail view; the level/expand split gives
fine-grained control over how much detail is revealed at each interaction.

## Visibility Resolution

When rendering a block, visibility is resolved through a priority chain:

1. **Programmatic vis_override** (highest priority): Set by the search system to force
   a block visible during search result navigation. Value: `ALWAYS_VISIBLE`.
2. **Per-block expanded override**: User's click state. Replaces the `expanded` component
   of the category VisState.
3. **Category filter state** (lowest priority): The category's current VisState from the
   view store.

For uncategorized blocks (category resolves to `None`), the result is always
`ALWAYS_VISIBLE` — they are never hidden by category filters.

The resolution produces a single `VisState` that is looked up in the truncation limits
table to determine the maximum number of rendered lines.

## Search Reveal

The search system can temporarily override a block's visibility to show search results
even when the block's category is hidden or collapsed. This uses the `vis_override`
field on `BlockViewState`, set to `ALWAYS_VISIBLE`.

Search reveal is **at most one block** (and optionally one region within that block)
at a time. Setting a new search reveal clears the previous one. Clearing search
reveal removes the override and restores normal category-based visibility.

Search reveal overrides are **not serialized** for hot-reload — they are transient
state that is regenerated by the search system.

## View Store

Category visibility state is stored in a reactive store with three keys per category:

- `vis:<category>` — `bool` — the visible flag
- `full:<category>` — `bool` — the full flag
- `exp:<category>` — `bool` — the expanded flag

A computed `active_filters` property assembles these 18 individual observables (6
categories x 3 flags) into a `dict[str, VisState]` keyed by category name. Any
change to any visibility key triggers re-rendering of the conversation view through
a single autorun reaction.

### Filtersets (Presets)

Named filterset presets can set all category visibility states at once. Presets are
applied via function keys or the `=`/`-` keys for cycling. Applying a preset batch-sets
all `vis:`, `full:`, and `exp:` keys and records the active filterset identifier.

Built-in filterset slots:

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

Note: F3 is skipped in the cycling order.

Filtersets are **not** user-configurable. They are hardcoded constants in `DEFAULT_FILTERSETS` in `settings.py`. The `filter:active` key defaults to `"1"` (Conversation preset) at startup.

Filterset cycling keys: `=` (next filterset) and `-` (previous filterset).

## View Overrides Store

Per-block and per-region mutable view state is stored in `ViewOverrides`, owned by
the `ConversationView` widget. This store is separate from the reactive view store
because it tracks fine-grained, block-level state that changes with click interactions
rather than category-level keyboard actions.

### Block View State

Per block (keyed by `block_id`):
- `expandable: bool` — set by the renderer; indicates the block exceeds its truncation limit
- `expanded: bool | None` — user click override; `None` means use category default
- `vis_override: VisState | None` — programmatic override (search reveal); not serialized

### Region View State

Per region (keyed by `(block_id, region_index)`):
- `expanded: bool | None` — click toggle override for collapsible regions within a block
- `strip_range: tuple[int, int] | None` — renderer-computed; maps region to strip lines

### Category Index

A `block_id → Category` index enables efficient clearing of all overrides for a
category in O(registered blocks in that category) time, rather than walking all
blocks.

### Serialization

Block and region view state (excluding `vis_override` and `strip_range`, which are
transient) is serialized for hot-reload state transfer via `to_dict()` / `from_dict()`.
This preserves user click expansions across code changes.

## Tool Summarization

At summary level (`visible=True, full=False`), consecutive tool use/result block
pairs within a turn are collapsed into a single `ToolUseSummaryBlock`. This summary
block carries aggregate tool counts and renders as a compact one-line overview.

At full level, individual `ToolUseBlock` and `ToolResultBlock` entries are shown with
their own content. At hidden level, tools produce no output.

The `ToolUseSummaryBlock` itself has 4 state-specific renderers:
- Summary collapsed: total count + top tool
- Summary expanded: total count + top 3 tools
- Full collapsed: short multi-line breakdown
- Full expanded: full sorted breakdown with percentages

## Footer Display

The footer shows current visibility state for each category as clickable chips.
Each chip displays the category's key number, name, and a state indicator. Chips
with `visible=True` have colored backgrounds matching their category indicator color.
Clicking a chip triggers `cycle_vis` for that category.

Categories are displayed in the footer in their registry order (key order: 1 through 6).
