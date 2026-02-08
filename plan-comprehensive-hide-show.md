# Plan: 3-Level Visibility System for All Block Types

## Context

The current filter system is binary (show/hide) and only 2 of 21 block types support expand/collapse. The user wants a uniform **3-level visibility** system — HIDDEN / SUMMARY / EXPANDED — across all block types, with per-category keyboard cycling and per-block click overrides. This replaces both the boolean filter system and the bespoke per-block collapse logic.

Also: remove turn selection (j/k/n/N/g/G) to simplify the UI. Make stats panel always visible, remove its shortcut.

---

## Part 1: Data Model

### 1.1 Visibility Enum

```python
# In formatting.py
class Visibility(IntEnum):
    HIDDEN = 0    # Block not rendered
    SUMMARY = 1   # Type-specific mid-level view
    EXPANDED = 2  # Full content
```

IntEnum so cycling is `(current + 1) % 3`.

### 1.2 Category Enum

```python
# In formatting.py
class Category(Enum):
    HEADERS = "headers"
    USER = "user"
    ASSISTANT = "assistant"
    TOOLS = "tools"
    SYSTEM = "system"
    METADATA = "metadata"
    BUDGET = "budget"
```

### 1.3 FormattedBlock Base Class

```python
@dataclass
class FormattedBlock:
    visibility: Visibility | None = None  # Per-block override. None = use category default.
    category: Category | None = None      # Context-dependent category. None = use BLOCK_CATEGORY.
    # Replaces: collapsed: bool = True
```

### 1.4 Category Resolution

Most blocks have a fixed category by type. A few (TextContentBlock, RoleBlock, ImageBlock, TextDeltaBlock) need context — set during formatting.

```python
# In rendering.py — static mapping for type-determined categories
BLOCK_CATEGORY: dict[str, Category | None] = {
    "SeparatorBlock": Category.HEADERS,
    "HeaderBlock": Category.HEADERS,
    "HttpHeadersBlock": Category.HEADERS,
    "MetadataBlock": Category.METADATA,
    "TurnBudgetBlock": Category.BUDGET,
    "SystemLabelBlock": Category.SYSTEM,
    "TrackedContentBlock": Category.SYSTEM,
    "ToolUseBlock": Category.TOOLS,
    "ToolResultBlock": Category.TOOLS,
    "ToolUseSummaryBlock": Category.TOOLS,
    "StreamInfoBlock": Category.METADATA,
    "StreamToolUseBlock": Category.TOOLS,
    "StopReasonBlock": Category.METADATA,
    # Context-dependent (use block.category field):
    "RoleBlock": None,
    "TextContentBlock": None,
    "TextDeltaBlock": None,
    "ImageBlock": None,
    # Always visible (no category):
    "ErrorBlock": None,
    "ProxyErrorBlock": None,
    "NewlineBlock": None,
    "UnknownTypeBlock": None,
}

def get_category(block: FormattedBlock) -> Category | None:
    if block.category is not None:
        return block.category
    return BLOCK_CATEGORY.get(type(block).__name__)
```

Set during formatting:
- `format_request()`: `TextContentBlock(category=Category.USER)`, `RoleBlock(category=Category.USER)`
- `format_response_event()`: `TextContentBlock(category=Category.ASSISTANT)`, `RoleBlock(category=Category.ASSISTANT)`
- System message blocks: `RoleBlock(category=Category.SYSTEM)`

### 1.5 Effective Visibility

```python
def effective_visibility(block: FormattedBlock, filters: dict[str, Visibility]) -> Visibility:
    """Per-block override > category default > EXPANDED."""
    if block.visibility is not None:
        return block.visibility
    cat = get_category(block)
    if cat and cat.value in filters:
        return filters[cat.value]
    return Visibility.EXPANDED
```

### 1.6 Filter State

Replace `dict[str, bool]` with `dict[str, Visibility]`:

```python
# app.py
vis_headers = reactive(Visibility.HIDDEN)
vis_user = reactive(Visibility.EXPANDED)
vis_assistant = reactive(Visibility.EXPANDED)
vis_tools = reactive(Visibility.SUMMARY)
vis_system = reactive(Visibility.SUMMARY)
vis_metadata = reactive(Visibility.HIDDEN)
vis_budget = reactive(Visibility.HIDDEN)
```

### 1.7 Keyboard Cycling

Single key cycles HIDDEN → SUMMARY → EXPANDED → HIDDEN:

| Key | Category | Default |
|-----|----------|---------|
| `h` | headers | HIDDEN |
| `u` | user | EXPANDED |
| `a` | assistant | EXPANDED |
| `t` | tools | SUMMARY |
| `s` | system | SUMMARY |
| `m` | metadata | HIDDEN |
| `e` | budget | HIDDEN |

Stats panel (`a` currently): make always visible, remove shortcut. Economics (`c`) and timeline (`l`) stay as panel toggles or move to command palette.

When a category cycles, **clear all per-block overrides** for that category (blocks revert to new default).

### 1.8 Per-Block Click Toggle

Click on a visible, expandable block (>PREVIEW_LINES strips):
- EXPANDED → set `block.visibility = Visibility.SUMMARY`
- SUMMARY → set `block.visibility = Visibility.EXPANDED`

Visual affordance: dim `▼` when expanded, dim `▶` when in summary. Collapsed indicator strip: `··· N more lines`.

---

## Part 2: What SUMMARY Means Per Category

SUMMARY is **type-specific**, not just "first 2 lines." Each category defines a meaningful mid-level representation:

| Category | HIDDEN | SUMMARY | EXPANDED |
|----------|--------|---------|----------|
| **headers** | Gone | Status line only (first line of HttpHeadersBlock) | All HTTP headers |
| **user** | Gone | First 2 lines of message text + `··· N more lines` | Full message |
| **assistant** | Gone | First 2 lines of message text + `··· N more lines` | Full message |
| **tools** | Gone | **ToolUseSummaryBlock**: `[used 3 tools: Read 2x, Bash 1x]` | Individual ToolUse/ToolResult blocks |
| **system** | Gone | Tag + status line: `[sp-1] NEW (245 chars):` (no content/diff) | Full content and diffs |
| **metadata** | Gone | (Typically 1 line — same as EXPANDED) | Model info, stop reason |
| **budget** | Gone | First line: `Context: 8.5k tok \| sys: 24% \| conv: 61%` | Full breakdown with cache stats |

### Implementation Strategy for SUMMARY

Two mechanisms, chosen per block type:

1. **Pre-pass transformation** (tools only): `collapse_tool_runs()` already creates ToolUseSummaryBlock — run it when tools = SUMMARY. This is a category-level structural transformation, not per-block.

2. **Generic strip truncation** (everything else): Render full content, truncate to PREVIEW_LINES (2) strips + indicator. Works for user/assistant text, headers, system prompts, budget. The first 2 lines of any block type naturally form a meaningful summary because the render functions are designed with the most important info first.

---

## Part 3: Rendering Changes

### 3.1 Single Enforcer: `render_turn_to_strips()`

All visibility logic moves here. Individual renderers become **pure** (block → Text, no filters).

```python
def render_turn_to_strips(blocks, filters, console, width, ...):
    # Pre-pass: tool summarization when tools = SUMMARY
    effective_blocks = _prepare_blocks(blocks, filters)

    for block_idx, block in effective_blocks:
        vis = effective_visibility(block, filters)
        if vis == Visibility.HIDDEN:
            continue

        renderer = BLOCK_RENDERERS.get(type(block).__name__)
        text = renderer(block)  # pure, no filters
        # ... render to strips ...

        # Track expandability
        block._expandable = len(block_strips) > PREVIEW_LINES

        # SUMMARY truncation (generic fallback)
        if vis == Visibility.SUMMARY and block._expandable:
            hidden = len(block_strips) - PREVIEW_LINES
            block_strips = block_strips[:PREVIEW_LINES] + [indicator_strip]

        all_strips.extend(block_strips)
```

### 3.2 Remove from Individual Renderers

- Remove all `if not filters.get(key): return None` checks
- Remove `is_expanded` / `collapsed` branching from `_render_tracked_content()` and `_render_turn_budget_block()`
- Drop `filters` param from renderer signatures: `(block) -> Text | None`

### 3.3 Cache Key

Cache stores full render (no visibility in key):
```python
cache_key = (id(block), width)
```

### 3.4 Filter Indicator

`_add_filter_indicator()` driven by `get_category(block)` in `render_turn_to_strips()`, not inside renderers. Need to extend the indicator color mapping to include the new `user` and `assistant` categories.

---

## Part 4: Remove Turn Selection

Remove from `widget_factory.py`:
- `_selected_turn`, `select_turn()`, `select_next_turn()`, `next_tool_turn()`, `jump_to_first()`, `jump_to_last()`, `_visible_turns()`
- Selection highlighting in `render_line()`

Remove from `app.py`:
- Bindings: j, k, n, N, g, G and their action handlers
- Stats toggle binding (make stats always visible)

Simplify `on_click()`: toggle expand only, no turn selection.

---

## Files to Modify

| File | Changes |
|------|---------|
| `formatting.py` | Add `Visibility` and `Category` enums. Replace `collapsed: bool` with `visibility: Visibility \| None = None` and `category: Category \| None = None` on FormattedBlock. |
| `formatting.py` | In `format_request()` / `format_response_event()`: set `category=` on TextContentBlock, RoleBlock, ImageBlock, TextDeltaBlock. |
| `rendering.py` | Replace `BLOCK_FILTER_KEY` with `BLOCK_CATEGORY`. Add `get_category()`, `effective_visibility()`, `PREVIEW_LINES`, `_make_collapse_indicator()`. Rewrite `render_turn_to_strips()` as single enforcer. Strip filter checks from all renderers. Drop `filters` from renderer signature. |
| `widget_factory.py` | `_is_expandable_block()` → check `block._expandable`. Remove turn selection code. Remove budget/collapsed sync from `rerender()`. Simplify `on_click()`. |
| `app.py` | Replace `show_*: reactive(bool)` with `vis_*: reactive(Visibility)`. Cycle actions instead of toggles. New `u`/`a` bindings. Remove j/k/n/N/g/G. Remove stats toggle. Update `active_filters`. |
| `custom_footer.py` | 3-state indicator per category (dim/half/bright or text labels). |
| `palette.py` | Add indicator colors for `user` and `assistant` categories. |
| Tests | Update filter assertions (bool → Visibility). Update render_block calls (no filters). Add 3-level visibility tests. |

---

## Verification

1. `uv run pytest` — all tests pass
2. `cc-dump --replay latest`:
   - `t` cycles tools: SUMMARY → EXPANDED → HIDDEN → SUMMARY
   - `s` cycles system: SUMMARY → EXPANDED → HIDDEN → SUMMARY
   - `u`/`a` cycle user/assistant content
   - Click long assistant text → toggles SUMMARY ↔ EXPANDED
   - 1-line blocks are NOT clickable
   - Tools SUMMARY shows `[used N tools: ...]` count line
   - System SUMMARY shows tag + status, no content
3. Footer shows 3-state per category
4. Streaming turns render fully regardless of visibility
5. Stats panel always visible without shortcut
