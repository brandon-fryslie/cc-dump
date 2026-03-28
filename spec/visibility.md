# Visibility System

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

The `Category` enum is defined in `formatting_impl.py`. METADATA consolidates the
former BUDGET, HEADERS, and METADATA categories into a single category.

### Category Assignment

A block's category is determined by a two-step resolution in `get_category()`:

1. **Dynamic category** (`block.category` field): Set during formatting when the block's
   category depends on context. For example, a `TextContentBlock` is assigned USER or
   ASSISTANT depending on which role's message it appears in.
2. **Static mapping** (`BLOCK_CATEGORY` dict, keyed by block type name): Used when
   `block.category` is `None`.

If both are `None`, the block is **always visible** — it has no category and receives
`ALWAYS_VISIBLE` from the visibility resolver. Examples: `ErrorBlock`, `ProxyErrorBlock`,
`NewlineBlock`.

Static category assignments (`BLOCK_CATEGORY` in `rendering_impl.py`):

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
| `TextContentBlock` | *dynamic* (USER, ASSISTANT, or SYSTEM via `block.category`) |
| `TextDeltaBlock` | *dynamic* (via `block.category`) |
| `ImageBlock` | *dynamic* (via `block.category`) |
| `MessageBlock` | *dynamic* (USER or ASSISTANT via `block.category`; `BLOCK_CATEGORY` maps to `None`) |
| `ConfigContentBlock` | `None` in `BLOCK_CATEGORY` — receives `ALWAYS_VISIBLE`, but parent rendering gates child processing |
| `HookOutputBlock` | `None` in `BLOCK_CATEGORY` — receives `ALWAYS_VISIBLE`, but parent rendering gates child processing |
| `ErrorBlock` | `None` (always visible) |
| `ProxyErrorBlock` | `None` (always visible) |
| `NewlineBlock` | `None` (always visible) |
| `UnknownTypeBlock` | `None` (always visible) |

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
| 5 | Full Expanded | `(True, True, True)` | unlimited (`None`) |

Two named constants:
- `HIDDEN = VisState(False, False, False)` — invisible
- `ALWAYS_VISIBLE = VisState(True, True, True)` — full expanded, used for uncategorized blocks and search reveal

### Truncation Limits

The `TRUNCATION_LIMITS` dict in `rendering_impl.py` maps every `VisState` to a max line
count (or `None` for unlimited). All 8 VisState combinations are present in the dict:

| VisState | Max Lines |
|----------|-----------|
| `(False, *, *)` (any hidden) | 0 |
| `(True, False, False)` — summary collapsed | 3 |
| `(True, False, True)` — summary expanded | 8 |
| `(True, True, False)` — full collapsed | 5 |
| `(True, True, True)` — full expanded | `None` (unlimited) |

When a block's rendered output exceeds its truncation limit, the block is marked
**expandable**. Expandable blocks show a visual indicator (arrow) and respond to
click interactions. Blocks that fit within their limit are not expandable and show
no arrow.

## Default Configuration

At startup, each category has a default VisState defined in `FILTER_SPECS`
(`core/filter_registry.py`):

| Key | Category | Default VisState | Effect |
|-----|----------|-----------------|--------|
| 1 | user | `(True, True, True)` | Full expanded — see all user input |
| 2 | assistant | `(True, True, True)` | Full expanded — see all responses |
| 3 | tools | `(True, False, False)` | Summary collapsed — compact tool view |
| 4 | system | `(True, False, False)` | Summary collapsed — system prompt previews |
| 5 | metadata | `(False, False, False)` | Hidden — clean view |
| 6 | thinking | `(True, False, False)` | Summary collapsed — thinking previews |

The `FILTER_SPECS` tuple is the canonical source. The view store schema is derived
from it: for each spec, three store keys are created (`vis:{name}`, `full:{name}`,
`exp:{name}`) initialized to the default's component values.

At startup, `filter:active` defaults to `"1"` (the Conversation preset), meaning the
Conversation filterset is conceptually active even though the individual category
defaults already match its values.

## Keyboard Controls

All keyboard input routes through a modal key dispatch system (`on_key` in `app.py`).
The `MODE_KEYMAP` dict in `input_modes.py` maps key characters to action names per
input mode. Visibility keys are available in NORMAL mode only (not during search
editing or search navigation).

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
- Toggle spec: `[("vis", None)]` — toggle the vis flag, touch nothing else.
- Example: tools at `(True, False, False)` -> press `3` -> `(False, False, False)` (hidden)
- Press `3` again -> `(True, False, False)` (back to summary collapsed)

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

Both the symbol keys and the shifted letter keys are mapped to the same action in
`MODE_KEYMAP`. The symbol keys also have alternate name mappings (e.g., `exclamation_mark`,
`at`, `number_sign`, `dollar_sign`, `percent_sign`, `circumflex_accent`) for terminal
compatibility.

**Behavior:** Forces `visible=True`, then toggles the `full` flag.

**State transitions for `toggle_detail`:**
- Toggle spec: `[("vis", True), ("full", None)]` — force visible, toggle full.
- Example: tools hidden at `(False, False, False)` -> press `#` -> `(True, True, False)` (full collapsed)
- Press `#` again -> `(True, False, False)` (summary collapsed)

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
- Toggle spec: `[("vis", True), ("exp", None)]` — force visible, toggle expanded.
- Example: tools at `(True, False, False)` -> press `e` -> `(True, False, True)` (summary expanded)
- Press `e` again -> `(True, False, False)` (summary collapsed)

### Footer Chip Clicks: 5-State Cycling (`cycle_vis`)

Clicking a category chip in the footer cycles through all 5 visibility states in order:

```
Hidden -> Summary Collapsed -> Summary Expanded -> Full Collapsed -> Full Expanded -> Hidden -> ...
```

The cycle is defined by `VIS_CYCLE` in `action_config.py` — a list of 5 VisState
values in the order above. The current state is looked up in the list; the next index
(modulo 5) determines the new state. If the current state is not found in the cycle
(e.g., a hidden state with non-default full/expanded), cycling advances to index 0
(Hidden).

### Toggle Spec Data Model

All three toggle operations (`toggle_vis`, `toggle_detail`, `toggle_analytics`) share
a single implementation `_toggle_vis_dicts()` driven by `VIS_TOGGLE_SPECS` — a dict
mapping spec keys to lists of `(store_key_prefix, force_value_or_None)` tuples:

```
VIS_TOGGLE_SPECS = {
    "vis":       [("vis", None)],                    # toggle visible
    "detail":    [("vis", True), ("full", None)],    # force visible, toggle full
    "analytics": [("vis", True), ("exp", None)],     # force visible, toggle expanded
}
```

When `force_value` is `None`, the current store value is toggled. Otherwise, the forced
value is set directly. Mutations are batched in a `transaction()` for a single autorun
fire.

### Override Clearing on State Change

Every keyboard toggle and chip cycle operation **clears all per-block expansion overrides**
for the affected category before applying the state change. The clearing happens via
`clear_overrides()` -> `ViewOverrides.clear_category()`, which resets both `expanded`
and `vis_override` on all blocks in the category, plus `expanded` on all regions of
those blocks. This ensures the new category state is the sole determinant of block
visibility — there are no stale block-level overrides leaking through from a previous
state.

The active filterset indicator (`filter:active`) is also set to `None` on any manual
visibility change, since the state no longer matches a named preset.

**Ordering:** Overrides are cleared *before* the transaction that updates store keys.
This ensures the autorun that fires on the transaction sees clean block state.

## Per-Block Expansion (Click Behavior)

Within a given category visibility state, individual blocks can be expanded or collapsed
by clicking. This is a **local adjustment** — it does not change the category state.

### Expandability

A block is **expandable** when its rendered output exceeds the truncation limit for
its current VisState. The rendering system sets the `expandable` flag on a block's
view state during rendering. Only expandable blocks respond to click interactions.

Expandability is determined by `_compute_expandable()` in `rendering_impl.py`, which
checks three conditions: (a) whether the block has children (hierarchical container),
(b) whether there is a different state-specific renderer for the expanded vs collapsed
state (identity comparison), or (c) whether the rendered strip count exceeds the
collapsed truncation limit for the current level.

### Click Toggling

Clicking an expandable block toggles its `expanded` override between `True` and
`False`. The expanded override replaces the category-level expanded state for that
specific block only.

- Clicking a collapsed expandable block -> sets `expanded=True` on its view state
- Clicking an expanded block -> sets `expanded=False`
- Clicking a non-expandable block -> no effect on expansion (stores click position
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

When rendering a block, visibility is resolved by `_resolve_visibility()` in
`rendering_impl.py` through a priority chain:

1. **Programmatic vis_override** (highest priority): Set by the search system to force
   a block visible during search result navigation. Value: `ALWAYS_VISIBLE`. When set,
   the entire VisState is replaced — no further resolution occurs.
2. **Per-block expanded override**: User's click state from `BlockViewState.expanded`.
   Replaces only the `expanded` component of the category VisState; `visible` and
   `full` remain as-is from the category filter.
3. **Category filter state** (lowest priority): The category's current VisState from
   `active_filters[cat.value]`.

For uncategorized blocks (category resolves to `None`), the result is always
`ALWAYS_VISIBLE` — they are never hidden by category filters.

The resolution produces a single `VisState` that is looked up in `TRUNCATION_LIMITS`
to determine the maximum number of rendered lines.

## Search Reveal

The search system can temporarily override a block's visibility to show search results
even when the block's category is hidden or collapsed. This uses the `vis_override`
field on `BlockViewState`, set to `ALWAYS_VISIBLE`.

Search reveal is **at most one block** (and optionally one region within that block)
at a time. The `ViewOverrides` object tracks the active reveal via `_active_reveal_block_id`
and `_active_reveal_region`. Setting a new search reveal via `set_search_reveal()`
clears the previous one first. Clearing search reveal via `clear_search_reveal()`
removes the override and restores normal category-based visibility.

When a region is included in the reveal, `set_search_reveal()` also sets
`expanded=True` on the region's `RegionViewState`, ensuring the region is open.
Clearing the reveal resets the region's `expanded` back to `None`.

Search reveal overrides are **not serialized** for hot-reload — they are transient
state that is regenerated by the search system.

## View Store

Category visibility state is stored in a reactive `HotReloadStore` created by
`view_store.create()`. Three keys per category:

- `vis:<category>` — `bool` — the visible flag
- `full:<category>` — `bool` — the full flag
- `exp:<category>` — `bool` — the expanded flag

This gives 18 observable keys for 6 categories (6 x 3). The schema is built
programmatically from `CATEGORY_CONFIG` (which is derived from `FILTER_SPECS`).

A computed `active_filters` property assembles these 18 individual observables into
a `dict[str, VisState]` keyed by category name. A single autorun watches
`active_filters` and triggers a full re-render of the conversation view:

```python
stx.autorun(app, lambda: (store.active_filters.get(), app._rerender_if_mounted()))
```

The helper `get_category_state(store, name)` reads the three keys and returns a
`VisState` for a single category.

### Filtersets (Presets)

Named filterset presets set all 6 categories at once. They are defined as
`DEFAULT_FILTERSETS` in `settings.py` — a dict mapping slot strings to
`dict[str, VisState]` keyed by category name.

Built-in filterset slots and names (from `FILTERSET_SLOTS` and `FILTERSET_NAMES`
in `action_config.py`):

| Slot | Label | Name |
|------|-------|------|
| `"1"` | F1 | Conversation |
| `"2"` | F2 | Overview |
| `"4"` | F4 | Tools |
| `"5"` | F5 | System |
| `"6"` | F6 | Cost |
| `"7"` | F7 | Full Debug |
| `"8"` | F8 | Assistant |
| `"9"` | F9 | Minimal |

Note: slot `"3"` is skipped — there is no F3 preset. `FILTERSET_SLOTS` lists them
in order `["1", "2", "4", "5", "6", "7", "8", "9"]` for cycling.

**Filterset values** (from `DEFAULT_FILTERSETS`):

| Slot | user | assistant | tools | system | metadata | thinking |
|------|------|-----------|-------|--------|----------|----------|
| 1 Conversation | Full Exp | Full Exp | Sum Col | Sum Col | Hidden | Sum Col |
| 2 Overview | Sum Col | Sum Col | Sum Col | Sum Col | Sum Col | Sum Col |
| 4 Tools | Sum Col | Sum Col | Full Exp | Hidden | Hidden | Hidden |
| 5 System | Sum Col | Sum Col | Hidden | Full Exp | Full Exp | Hidden |
| 6 Cost | Sum Col | Sum Col | Sum Col | Hidden | Full Exp | Hidden |
| 7 Full Debug | Full Exp | Full Exp | Full Exp | Full Exp | Full Exp | Full Exp |
| 8 Assistant | Hidden | Full Exp | Hidden | Hidden | Hidden | Hidden |
| 9 Minimal | Sum Col | Sum Col | Sum Col | Hidden | Hidden | Hidden |

### Filterset Application

`apply_filterset(app, slot)` in `action_handlers.py`:
1. Loads the VisState dict from `settings.get_filterset(slot)`.
2. Batch-sets all 18 store keys via `store.update(updates)`.
3. Sets `filter:active` to the slot string.
4. Shows a notification with the label (e.g., "F1 Conversation").

### Filterset Cycling

- `=` key: `next_filterset` — advances to the next slot in `FILTERSET_SLOTS`
- `-` key: `prev_filterset` — moves to the previous slot

Both use `_cycle_filterset(app, direction)` which reads the current `filter:active`
slot, finds its index in `FILTERSET_SLOTS`, and advances by `direction` (+1 or -1)
with modulo wrapping. If the current slot is not found in the list (e.g., `None`
from manual changes), cycling starts from index -1, which wraps to the first slot
(for +1) or the seventh slot (for -1).

**F1-F9 function keys** are listed in the keys help panel as "Load preset" but are
**not bound** in `MODE_KEYMAP`. The only way to access filtersets via keyboard is
through `=`/`-` cycling. The `action_apply_filterset` method exists on the app but
is only called internally by the cycling handlers.

### Filterset Invalidation

Any manual visibility change (toggle or cycle) sets `filter:active` to `None`,
indicating the current state no longer matches any named preset. This is a visual
indicator only — it does not affect visibility behavior.

Filtersets are **not** user-configurable. They are hardcoded constants.

## View Overrides Store

Per-block and per-region mutable view state is stored in `ViewOverrides`
(`view_overrides.py`), owned by the `ConversationView` widget. This store is separate
from the reactive view store because it tracks fine-grained, block-level state that
changes with click interactions rather than category-level keyboard actions.

### Block View State

Per block (keyed by `block_id`), stored as `BlockViewState` dataclass:
- `expandable: bool` (default `False`) — set by the renderer; indicates the block exceeds its truncation limit
- `expanded: bool | None` (default `None`) — user click override; `None` means use category default
- `vis_override: VisState | None` (default `None`) — programmatic override (search reveal); not serialized

Access: `get_block(block_id)` auto-creates on miss. `block_state(block_id)` returns
`None` if no entry exists (read-only probe).

### Region View State

Per region (keyed by `(block_id, region_index)`), stored as `RegionViewState` dataclass:
- `expanded: bool | None` (default `None`) — click toggle override for collapsible regions within a block
- `strip_range: tuple[int, int] | None` (default `None`) — renderer-computed; maps region to strip lines; not serialized

Access: `get_region(block_id, idx)` auto-creates on miss.

### Category Index

A `_block_categories: dict[int, Category | None]` index maps `block_id` to `Category`.
Populated by `register_block()` / `unregister_block()` calls from the rendering
pipeline. Enables `clear_category()` to reset all overrides for a category in
O(registered blocks in that category) time.

`clear_category(category)` resets:
- `expanded = None` and `vis_override = None` on all blocks matching the category
- `expanded = None` on all regions whose block matches the category
- If the active search reveal was in the cleared category, the reveal tracking is
  also cleared (but the actual `BlockViewState` fields are already reset above)

### Serialization

`to_dict()` serializes block and region state for hot-reload transfer:
- Block entries include `expandable` and `expanded` (both only when non-default)
- Region entries include `expanded` (only when non-None)
- `vis_override` and `strip_range` are transient — **not serialized**
- `_block_categories` is transient — **not serialized** (rebuilt by renderer)

`from_dict(data)` reconstructs a `ViewOverrides` from serialized state.

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
Each chip displays the category's key number, name, and a state separator dot
(e.g., " 3 tools . "). Chips are composed in `custom_footer.py` from
`CATEGORY_ITEMS` (derived from `FILTER_SPECS`), which provides `(key, name)` pairs
in registry order.

Clicking a chip dispatches `app.cycle_vis('{name}')`, triggering the 5-state cycle
for that category.

Categories are displayed in the footer in their registry order (key order: 1 through 6).

## Source References

| Source File | What It Defines |
|-------------|----------------|
| `src/cc_dump/core/formatting_impl.py` | `Category` enum, `VisState` named tuple, `HIDDEN`, `ALWAYS_VISIBLE` |
| `src/cc_dump/core/filter_registry.py` | `FilterSpec`, `FILTER_SPECS` (canonical defaults), `CATEGORY_CONFIG`, `CATEGORY_ITEMS` |
| `src/cc_dump/tui/rendering_impl.py` | `TRUNCATION_LIMITS`, `BLOCK_CATEGORY`, `get_category()`, `_resolve_visibility()` |
| `src/cc_dump/tui/action_config.py` | `VIS_CYCLE`, `VIS_TOGGLE_SPECS`, `FILTERSET_SLOTS`, `FILTERSET_NAMES` |
| `src/cc_dump/tui/action_handlers.py` | `toggle_vis`, `toggle_detail`, `toggle_analytics`, `cycle_vis`, `apply_filterset`, `next_filterset`, `prev_filterset` |
| `src/cc_dump/app/view_store.py` | Store schema, `active_filters` computed, `get_category_state()` |
| `src/cc_dump/tui/view_overrides.py` | `BlockViewState`, `RegionViewState`, `ViewOverrides` |
| `src/cc_dump/tui/input_modes.py` | `MODE_KEYMAP` (key bindings per mode) |
| `src/cc_dump/io/settings.py` | `DEFAULT_FILTERSETS` |
| `src/cc_dump/tui/custom_footer.py` | Footer chip composition and click dispatch |
