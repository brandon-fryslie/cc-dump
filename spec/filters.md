# Filters

> Status: draft
> Last verified against: not yet

## Overview

Claude Code API traffic is dense. A single conversation turn can contain system prompts, tool definitions, user messages, assistant responses, tool use/result pairs, thinking blocks, token budgets, HTTP headers, and request metadata. Showing everything at full detail all the time would make the TUI unusable — the signal drowns in noise.

The filter system exists to let users control what they see and how much of it. It operates on two axes: **category visibility** (which kinds of content appear) and **detail level** (how much of each kind is shown). Users can toggle individual categories, cycle through detail levels, or switch between named presets that configure everything at once. The goal is fast, keyboard-driven control over information density without losing access to anything.

This spec covers the filter data model, the category registry, filtersets (presets), per-block overrides, and how filter state flows into the rendering pipeline.

## Filter Data Model

### VisState

`VisState` is a named tuple with three boolean axes. It is the single representation of visibility for any content category or block.

```
VisState(visible: bool, full: bool, expanded: bool)
```

| Axis | `False` | `True` |
|------|---------|--------|
| `visible` | Hidden — produces zero lines | Shown |
| `full` | Summary level — truncated rendering | Full level — complete rendering |
| `expanded` | Collapsed — tighter truncation limits | Expanded — looser or no truncation limits |

These three booleans produce 8 combinations, but only 5 are meaningful states in the visibility cycle. The 3 hidden states (where `visible=False`) all produce 0 lines regardless of the other axes.

**Canonical constants:**

| Name | Value | Meaning |
|------|-------|---------|
| `HIDDEN` | `(False, False, False)` | Invisible |
| `ALWAYS_VISIBLE` | `(True, True, True)` | Full, expanded — used for uncategorized blocks |

**Source:** `src/cc_dump/core/formatting_impl.py`

### Category

Six content categories group all blocks for visibility control:

| Category | Content |
|----------|---------|
| `USER` | User message content |
| `ASSISTANT` | Assistant response content |
| `TOOLS` | Tool use blocks and tool result blocks |
| `SYSTEM` | System prompt content |
| `METADATA` | Token budgets, HTTP headers, request/response metadata (consolidates former BUDGET, HEADERS, and METADATA categories) |
| `THINKING` | Extended thinking / reasoning blocks |

Every `FormattedBlock` is assigned to exactly one category, or to no category (meaning it is always visible and not subject to filtering). Category assignment is resolved by `get_category()` in rendering, which checks the block's `.category` field first (set at formatting time for context-dependent blocks), then falls back to the static `BLOCK_CATEGORY` mapping keyed by block type name.

**Source:** `src/cc_dump/core/formatting_impl.py` (Category enum), `src/cc_dump/tui/rendering_impl.py` (BLOCK_CATEGORY mapping, get_category)

## Filter Registry

The `FilterSpec` named tuple binds together everything about a filter category in one place:

```
FilterSpec(key: str, name: str, description: str, default: VisState, indicator_index: int)
```

| Field | Purpose |
|-------|---------|
| `key` | Keyboard key for the category (e.g., `"1"` for user) |
| `name` | Category name string (matches `Category` enum value) |
| `description` | Display label |
| `default` | Initial `VisState` on app startup |
| `indicator_index` | Position in the footer indicator palette |

The `FILTER_SPECS` tuple is the single source of truth. All other shapes are derived:

- `CATEGORY_CONFIG` — `list[tuple[str, str, str, VisState]]` for backward compatibility (a list, not a tuple of tuples)
- `CATEGORY_ITEMS` — `(key, name)` pairs in key order for the footer row
- `FILTER_INDICATOR_INDEX` — name → indicator position mapping
- `FILTER_INDICATOR_NAMES` — names in indicator-index order

**Default visibility states:**

| Category | Default VisState | Meaning |
|----------|-----------------|---------|
| user | `(True, True, True)` | Full expanded |
| assistant | `(True, True, True)` | Full expanded |
| tools | `(True, False, False)` | Summary collapsed |
| system | `(True, False, False)` | Summary collapsed |
| metadata | `(False, False, False)` | Hidden |
| thinking | `(True, False, False)` | Summary collapsed |

**Source:** `src/cc_dump/core/filter_registry.py`

## View Store: Reactive Filter State

Filter state lives in the view store (`src/cc_dump/app/view_store.py`), a `HotReloadStore` with observable keys. Each category gets three store keys:

- `vis:{name}` — boolean, maps to `VisState.visible`
- `full:{name}` — boolean, maps to `VisState.full`
- `exp:{name}` — boolean, maps to `VisState.expanded`

This gives 18 observable keys for 6 categories (6 × 3).

The `active_filters` computed assembles these 18 observables into a single `dict[str, VisState]` keyed by category name. Any change to any of the 18 keys triggers recomputation. A single autorun watches `active_filters` and triggers a full re-render of the conversation view.

The store key `filter:active` tracks which filterset preset is currently applied (as a slot string like `"1"`) or `None` if the user has manually adjusted individual categories since applying a preset. The startup default is `"1"` (the Conversation preset).

## Filtersets (Presets)

Filtersets are named configurations that set all 6 categories at once. They are accessed via function keys (F1–F9, mapped to slots `"1"`–`"9"`, skipping `"3"`).

| Slot | Name | user | assistant | tools | system | metadata | thinking |
|------|------|------|-----------|-------|--------|----------|----------|
| F1 | Conversation | Full Exp | Full Exp | Sum Col | Sum Col | Hidden | Sum Col |
| F2 | Overview | Sum Col | Sum Col | Sum Col | Sum Col | Sum Col | Sum Col |
| F4 | Tools | Sum Col | Sum Col | Full Exp | Hidden | Hidden | Hidden |
| F5 | System | Sum Col | Sum Col | Hidden | Full Exp | Full Exp | Hidden |
| F6 | Cost | Sum Col | Sum Col | Sum Col | Hidden | Full Exp | Hidden |
| F7 | Full Debug | Full Exp | Full Exp | Full Exp | Full Exp | Full Exp | Full Exp |
| F8 | Assistant | Hidden | Full Exp | Hidden | Hidden | Hidden | Hidden |
| F9 | Minimal | Sum Col | Sum Col | Sum Col | Hidden | Hidden | Hidden |

Applying a filterset batch-sets all 18 store keys in one transaction and records the active slot in `filter:active`. The slot label appears in a footer notification.

Cycling between filtersets uses `=` (`next_filterset`) and `-` (`prev_filterset`) to move forward/backward through the slot list.

**Source:** `src/cc_dump/io/settings.py` (DEFAULT_FILTERSETS), `src/cc_dump/tui/action_config.py` (FILTERSET_SLOTS, FILTERSET_NAMES), `src/cc_dump/tui/action_handlers.py` (apply_filterset, next_filterset, prev_filterset)

## User Interactions

### Per-Category Controls

Each category can be manipulated independently via keyboard:

| Action | Effect | Implementation |
|--------|--------|----------------|
| Number key (`1`–`6`) | Toggle `visible` | `toggle_vis` — flips `vis:{name}` |
| Shift+number | Toggle `full` (forces `visible=True`) | `toggle_detail` — sets `vis:{name}=True`, flips `full:{name}` |
| Letter key (`q`/`w`/`e`/`r`/`t`/`y`) | Toggle `expanded` (forces `visible=True`) | `toggle_analytics` — sets `vis:{name}=True`, flips `exp:{name}` |
| Click on footer chip | Cycle through 5 visibility states | `cycle_vis` — advances through VIS_CYCLE |

### Visibility Cycle

`cycle_vis` progresses through 5 ordered states:

1. **Hidden** — `(False, False, False)` — category produces zero output
2. **Summary Collapsed** — `(True, False, False)` — truncated to 3 lines
3. **Summary Expanded** — `(True, False, True)` — truncated to 8 lines
4. **Full Collapsed** — `(True, True, False)` — truncated to 5 lines
5. **Full Expanded** — `(True, True, True)` — unlimited lines

After state 5, it wraps back to state 1. Any manual toggle or cycle clears the `filter:active` slot (the user has departed from the preset).

### Override Clearing

When a category's visibility state changes (via toggle or cycle), all per-block expansion overrides for that category are cleared. This prevents stale click-to-expand state from conflicting with the new category-level setting.

**Source:** `src/cc_dump/tui/action_config.py` (VIS_CYCLE, VIS_TOGGLE_SPECS), `src/cc_dump/tui/action_handlers.py`

## Per-Block View Overrides

Beyond category-level filters, individual blocks can have view state overrides stored in `ViewOverrides`, owned by the `ConversationView` widget.

### BlockViewState

Per-block overrides (keyed by `block_id`):

| Field | Type | Meaning |
|-------|------|---------|
| `expandable` | `bool` | Renderer-computed: whether the block has enough content to expand |
| `expanded` | `bool \| None` | User click override; `None` means use category default |
| `vis_override` | `VisState \| None` | Programmatic override (search reveal); takes absolute priority |

### RegionViewState

Per-region overrides (keyed by `(block_id, region_index)`):

| Field | Type | Meaning |
|-------|------|---------|
| `expanded` | `bool \| None` | Click toggle for independently expandable regions within a block |
| `strip_range` | `tuple[int, int] \| None` | Renderer-computed strip range (transient) |

### Search Reveal

When the user navigates search results, the search system can force a block (and optionally a specific region) to be visible regardless of the current category filter state. This uses `vis_override = ALWAYS_VISIBLE` on the block's `BlockViewState`. At most one block + region can have an active search reveal at a time — setting a new reveal clears the previous one.

Search reveal is transient: it is not serialized during hot-reload, and it is cleared when the search session ends.

### Category Index

`ViewOverrides` maintains a `_block_categories` dict mapping `block_id → Category` for efficient category-scoped clearing. When a category's visibility changes, `clear_category()` resets all block and region overrides for matching blocks in O(registered blocks in category) rather than walking the entire block tree.

**Source:** `src/cc_dump/tui/view_overrides.py`

## Interaction with the Rendering Pipeline

Filter state enters the rendering pipeline at one point: `_resolve_visibility()` in `rendering_impl.py`. This is the single enforcer for visibility decisions.

### Resolution Priority

For each block, visibility is resolved with this priority order (highest wins):

1. **Programmatic vis_override** — `BlockViewState.vis_override` (e.g., search reveal). When set, this `VisState` is used directly.
2. **User expanded override** — `BlockViewState.expanded` overrides the `expanded` axis of whatever VisState was resolved from the category filter.
3. **Category filter** — the `VisState` from `active_filters[category_name]`.
4. **Uncategorized default** — blocks with no category get `ALWAYS_VISIBLE`.

The resolved `VisState` is then used to:

1. **Look up truncation limits** — `TRUNCATION_LIMITS[vis]` returns the maximum number of rendered lines (or `None` for unlimited):

   | VisState | Max Lines |
   |----------|-----------|
   | Any hidden state | 0 |
   | Summary Collapsed | 3 |
   | Summary Expanded | 8 |
   | Full Collapsed | 5 |
   | Full Expanded | unlimited |

2. **Select the renderer** — The unified renderer registry is keyed by `(block_type_name, visible, full, expanded)`. State-specific renderers can produce fundamentally different output for the same block type at different visibility levels (e.g., a tool use block might show just the tool name at summary level vs. the full input JSON at full level).

3. **Determine expandability** — After rendering, the pipeline checks whether the block would look different if expanded (either different renderer or enough lines to exceed the collapsed limit). This sets `BlockViewState.expandable`, which gates click-to-expand interaction.

4. **Recurse into children** — Child block visibility is resolved independently. A visible parent with hidden children renders the parent's own content but skips the children.

### Render Flow

```
render_turn_to_strips(blocks, filters, ...)
  └─ for each block: _render_block_tree(block, ctx)
       ├─ _resolve_visibility(block, ctx.filters, ctx.overrides) → VisState
       ├─ TRUNCATION_LIMITS[vis] → max_lines (0 = skip entirely)
       ├─ RENDERERS[(type, vis)] → renderer function → strips
       ├─ truncate to max_lines if needed
       ├─ compute expandability
       └─ recurse into children
```

The `filters` dict is passed through a `_RenderContext` and is read-only during rendering. All mutations to filter state happen in the view store; rendering is a pure projection of that state.

### Re-render Triggers

A re-render of the conversation view happens when:

- `active_filters` computed changes (any of the 18 store keys mutated)
- A per-block override changes (click-to-expand, search reveal)
- The view width changes (terminal resize)
- Theme changes (theme generation counter in store)

The `TurnData.re_render()` method snapshots the relevant filter keys for each turn and short-circuits if the snapshot hasn't changed, avoiding redundant work for turns whose visible categories were not affected.

**Source:** `src/cc_dump/tui/rendering_impl.py` (_resolve_visibility, TRUNCATION_LIMITS, RENDERERS, _render_block_tree)

## Contracts

1. **VisState is the single visibility representation.** All visibility decisions flow through `VisState` values. There is no parallel "level" integer or "is_hidden" boolean — those semantics are encoded in the three axes.

2. **FilterSpec registry is the single source of category metadata.** Key bindings, names, defaults, and indicator positions are all derived from `FILTER_SPECS`. Adding a category means adding one `FilterSpec` entry.

3. **`_resolve_visibility` is the single enforcer for visibility.** No other code path decides whether a block is visible. The priority chain (vis_override > expanded override > category filter > uncategorized default) is evaluated in one place.

4. **Category changes clear block overrides.** Toggling or cycling a category resets all per-block expansion overrides for that category. This prevents stale per-block state from producing confusing visual results after a category-level change.

5. **Filtersets are atomic.** Applying a filterset sets all 18 keys in one transaction, producing a single autorun fire and one re-render. There is no intermediate state where some categories reflect the new preset and others don't.

6. **Search reveal overrides filter state, not store state.** Search reveal uses `vis_override` on the block's view state, not by mutating the category filter keys. This means the category filters are unmodified and the reveal is automatically scoped to one block at a time.

7. **Rendering is a pure projection.** The render pass reads filter state and overrides but never mutates them (except for computing `expandable` and `strip_range`, which are renderer-owned derived fields).
