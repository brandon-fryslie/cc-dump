# FINAL PLAN: cc-dump-6pv — Immutable Response Domain Store + View Override Extraction

**Ticket:** cc-dump-6pv (P1)
**Dependency:** cc-dump-yj3 must be closed (done at `ff55efb`)

## 1. Problem Statement

FormattedBlock dataclasses carry **four categories of mutable view state** that violate domain/view separation:

| Mutable field | Declared? | Writers | Readers |
|---|---|---|---|
| `block.expanded: bool\|None` | Yes (dataclass field) | widget_factory:1259, action_handlers:55, search_controller:389 | rendering:398, widget_factory:1253 |
| `block._force_vis: VisState\|None` | **No** (monkey-patched) | search_controller:352,359,388 | rendering:388, rendering:1886 |
| `block._expandable: bool` | **No** (monkey-patched) | rendering:2082 | widget_factory:919, rendering:2106,2113,2122 |
| `region.expanded: bool\|None` | Yes (ContentRegion field) | widget_factory:1226, action_handlers:57 | rendering:837,1138,1144,1969 |
| `region._strip_range: tuple\|None` | Yes (ContentRegion field) | rendering:1999 | widget_factory:1180,1202-1204 |

**Consequence:** Domain objects are mutated by 4 separate TUI modules. They cannot be shared across subscribers (analytics, HAR recorder). Hot-reload survives only because block objects are passed by reference. `id(block)` as cache key couples cache to object lifetime.

**Confirmed non-consumers:** HAR recorder, analytics store, event_handlers — none read any of these fields. The mutation is exclusively a TUI concern.

## 2. Architecture Constraints

// [LAW:one-source-of-truth] View overrides have exactly one store — ViewOverrides.
// [LAW:single-enforcer] Visibility resolution reads overrides at one site — `_resolve_visibility()`.
// [LAW:dataflow-not-control-flow] FormattedBlock carries domain data; ViewOverrides carries view data. The pipeline always runs both; values decide rendering, not conditionals about where to look.
// [LAW:one-way-deps] formatting.py → rendering.py → widget_factory.py. ViewOverrides sits beside rendering (same layer), owned by ConversationView.

## 3. Design

### 3.1 Block Identity

Auto-incrementing `block_id: int` on FormattedBlock, assigned at creation. Replaces `id(block)` in cache keys. Addressed as `(block_id,)` for blocks, `(block_id, region_index)` for regions.

```python
# formatting.py
_next_block_id: int = 0

def _auto_id() -> int:
    global _next_block_id
    _next_block_id += 1
    return _next_block_id

@dataclass
class FormattedBlock:
    block_id: int = field(default_factory=_auto_id)
    # ... all existing domain fields unchanged during Phase 1-2 ...
```

### 3.2 ViewOverrides

Plain dict-based container (not snarfx Store — too granular for 1000s of blocks per render pass). Lives on `ConversationView`. Serializable for hot-reload.

```python
# src/cc_dump/tui/view_overrides.py (new file)
@dataclass
class BlockViewState:
    expanded: bool | None = None       # click toggle override
    force_vis: VisState | None = None  # search override
    expandable: bool = False           # renderer-computed

@dataclass
class RegionViewState:
    expanded: bool | None = None              # click toggle override
    strip_range: tuple[int, int] | None = None  # renderer-computed

class ViewOverrides:
    _blocks: dict[int, BlockViewState]           # block_id → state
    _regions: dict[tuple[int, int], RegionViewState]  # (block_id, region_idx) → state
    _search_block_ids: set[int]                  # track force_vis'd blocks for bulk clear

    def get_block(self, block_id: int) -> BlockViewState: ...    # auto-create on miss
    def get_region(self, block_id: int, idx: int) -> RegionViewState: ...
    def clear_category(self, blocks: Iterable[FormattedBlock], category: Category) -> None: ...
    def clear_search(self) -> None: ...    # bulk-clear all force_vis using _search_block_ids
    def to_dict(self) -> dict: ...         # for hot-reload get_state()
    @classmethod
    def from_dict(cls, data: dict) -> "ViewOverrides": ...  # for restore_state()
```

### 3.3 Threading Through the Pipeline

```
render_turn_to_strips(blocks, filters, ..., overrides: ViewOverrides)
  → _RenderContext gains `overrides: ViewOverrides` field
    → _resolve_visibility(block, filters, overrides) reads force_vis + expanded
    → _render_block_tree writes expandable, strip_range to overrides
    → _render_region_parts / _render_tool_def_region_parts receive overrides
      → read region.expanded from overrides instead of ContentRegion

ConversationView owns ViewOverrides
  → _toggle_block_expand writes to overrides
  → _toggle_region writes to overrides
  → _is_expandable_block reads from overrides
  → _region_at_line / _region_tag_at_line reads strip_range from overrides

search_controller accesses overrides via conv._view_overrides
  → navigate_to_current writes force_vis to overrides
  → clear_search_expand calls overrides.clear_search()

action_handlers accesses overrides via conv._view_overrides
  → clear_overrides calls overrides.clear_category()
```

## 4. File-by-File Implementation Steps

### Phase 1: Additive Foundation (no behavior change)

**Step 1.1 — `src/cc_dump/formatting.py`**
- Add `_next_block_id` counter + `_auto_id()` factory
- Add `block_id: int = field(default_factory=_auto_id)` to FormattedBlock
- No other changes; all existing code still works

**Step 1.2 — `src/cc_dump/tui/view_overrides.py` (new)**
- Create `BlockViewState`, `RegionViewState` dataclasses
- Create `ViewOverrides` class with all methods
- `to_dict()` / `from_dict()` for serialization
- Import only `cc_dump.formatting` (VisState, Category, FormattedBlock for type hints)
- Unit tests: `tests/test_view_overrides.py` (new)

**Step 1.3 — `src/cc_dump/tui/widget_factory.py`**
- `ConversationView.__init__`: add `self._view_overrides = ViewOverrides()`
- `get_state()`: add `"view_overrides": self._view_overrides.to_dict()`
- `restore_state()`: add `self._view_overrides = ViewOverrides.from_dict(state.get("view_overrides", {}))`
- Property: `@property def view_overrides(self) -> ViewOverrides`

**Step 1.4 — `src/cc_dump/hot_reload.py`** (if needed)
- Verify `view_overrides.py` is classified correctly (RELOADABLE, in tui/ — auto-detected)
- No changes expected; hot-reload preserves ConversationView state via get_state/restore_state

### Phase 2: Dual-Read Migration (backward-compatible)

**Step 2.1 — `src/cc_dump/tui/rendering.py` (visibility reads)**
- `_resolve_visibility()`: add `overrides: ViewOverrides | None = None` parameter
  - Read `force_vis` from `overrides.get_block(block.block_id).force_vis` if overrides, else `getattr(block, "_force_vis", None)`
  - Read `expanded` from `overrides.get_block(block.block_id).expanded` if overrides, else `block.expanded`
- `_RenderContext`: add `overrides: ViewOverrides | None` field
- `_render_block_tree()`: pass `ctx.overrides` to `_resolve_visibility()`

**Step 2.2 — `src/cc_dump/tui/rendering.py` (render writes)**
- `_render_block_tree()`: write `_expandable` to `ctx.overrides.get_block(block.block_id).expandable` AND `block._expandable` (dual-write)
- `_render_block_tree()` region path: write `strip_range` to `ctx.overrides.get_region(block.block_id, region.index).strip_range` AND `region._strip_range` (dual-write)
- Cache keys: replace `id(block)` with `block.block_id` (2 locations, lines 1972, 2047)
- Region cache state: read from `overrides.get_region()` instead of `region.expanded` (with fallback)

**Step 2.3 — `src/cc_dump/tui/rendering.py` (region renderers)**
- `_render_region_parts()`: add `overrides: ViewOverrides | None = None` parameter
  - Read `region.expanded` from overrides if available, else ContentRegion field
- `_render_tool_def_region_parts()`: same treatment
- `_REGION_PART_RENDERERS` function signatures updated (both renderers)
- Call sites in `_render_block_tree()` pass `ctx.overrides`

**Step 2.4 — `src/cc_dump/tui/rendering.py` (entry point)**
- `render_turn_to_strips()`: add `overrides: ViewOverrides | None = None` parameter
- Pass to `_RenderContext`
- All callers updated:
  - `widget_factory.py`: `TurnData.re_render()`, `ConversationView.add_turn()`, `finalize_streaming_turn()`, `_rebuild_from_state()`, `on_resize()` — pass `self._view_overrides`
  - `widget_factory.py`: `ensure_turn_rendered()` — pass `self._view_overrides`

**Step 2.5 — `src/cc_dump/tui/widget_factory.py` (click handlers)**
- `_toggle_block_expand()`: write `self._view_overrides.get_block(block.block_id).expanded = ...` AND `block.expanded = ...` (dual-write)
- `_toggle_region()`: write to `self._view_overrides.get_region(block.block_id, region_idx).expanded = ...` AND `region.expanded = ...` (dual-write)
- `_is_expandable_block()`: read from `self._view_overrides.get_block(block.block_id).expandable` with fallback to `getattr(block, "_expandable", False)`
- `_region_at_line()`: read `strip_range` from `self._view_overrides.get_region()` with fallback to `region._strip_range`
- `_region_tag_at_line()`: same treatment

**Step 2.6 — `src/cc_dump/tui/search_controller.py`**
- `navigate_to_current()`: write `conv._view_overrides.get_block(block.block_id).force_vis = ALWAYS_VISIBLE` AND `block._force_vis = ALWAYS_VISIBLE` (dual-write)
- Also record `block.block_id` in `conv._view_overrides._search_block_ids`
- `expanded_blocks` list entries: add `block_id` to tuple — `(turn_idx, block_idx, block_ref, block_id)`
- `clear_search_expand()`: call `conv._view_overrides.clear_search()` AND still do `block_ref._force_vis = None; block_ref.expanded = None` (dual-write)

**Step 2.7 — `src/cc_dump/tui/action_handlers.py`**
- `clear_overrides()`: call `conv._view_overrides.clear_category(blocks, cat)` AND still walk blocks setting `block.expanded = None` (dual-write)

**Step 2.8 — Run full test suite, verify zero behavioral change**

### Phase 3: Remove Block-Level View State (breaking, after Phase 2 verified)

**Step 3.1 — `src/cc_dump/formatting.py`**
- Remove `expanded: bool | None = None` from `FormattedBlock`
- Remove `expanded: bool | None = None` from `ContentRegion`
- Remove `_strip_range: tuple[int, int] | None = None` from `ContentRegion`
- Keep `content_regions: list[ContentRegion]` on FormattedBlock (domain data: kind, tags, index)

**Step 3.2 — `src/cc_dump/tui/rendering.py`**
- `_resolve_visibility()`: remove fallback to `block.expanded` / `getattr(block, "_force_vis")`. `overrides` parameter becomes required (not Optional)
- `_render_block_tree()`: remove dual-writes to `block._expandable`, `region._strip_range`
- `_render_region_parts()` / `_render_tool_def_region_parts()`: remove fallback to `region.expanded`. `overrides` parameter becomes required
- Region cache state: read exclusively from ViewOverrides

**Step 3.3 — `src/cc_dump/tui/widget_factory.py`**
- `_toggle_block_expand()`: remove `block.expanded = ...` dual-write
- `_toggle_region()`: remove `region.expanded = ...` dual-write
- `_is_expandable_block()`: remove `getattr(block, "_expandable")` fallback
- `_region_at_line()` / `_region_tag_at_line()`: remove `region._strip_range` fallback

**Step 3.4 — `src/cc_dump/tui/search_controller.py`**
- `navigate_to_current()`: remove `block._force_vis = ALWAYS_VISIBLE` dual-write
- `clear_search_expand()`: remove `block_ref._force_vis = None; block_ref.expanded = None`. Only call `conv._view_overrides.clear_search()`
- `expanded_blocks` entries: remove `block_ref` from tuple — store `(turn_idx, block_idx, block_id)` only

**Step 3.5 — `src/cc_dump/tui/action_handlers.py`**
- `clear_overrides()`: remove block-walking `block.expanded = None` / `region.expanded = None`. Only call `conv._view_overrides.clear_category()`

**Step 3.6 — Update tests**
- `tests/test_hot_reload.py`:
  - `test_conversation_view_blocks_preserve_expansion` → test via ViewOverrides in get_state/restore_state
  - `test_conversation_view_blocks_preserve_force_vis` → test via ViewOverrides serialization
  - `test_conversation_view_content_regions_survive` → region expanded state via ViewOverrides
- `tests/test_xml_collapse.py`: all `region.expanded = False` → set via ViewOverrides or pass overrides to render calls
- `tests/test_tool_rendering.py`: `test_force_vis_override_emits_individual` → set via ViewOverrides
- `tests/test_gutter_rendering.py`: no changes needed (tests use filters dict, not block-level expanded)

**Step 3.7 — Run full test suite, verify zero behavioral change**

## 5. Acceptance Criteria (Machine-Verifiable)

### New Invariant Tests (`tests/test_view_overrides.py`)

| # | Test | Assertion |
|---|---|---|
| AC1 | `test_block_id_unique_in_turn` | `format_request()` → all block_ids in tree are unique |
| AC2 | `test_block_id_monotonic` | Two `format_request()` calls → second batch block_ids > first batch max |
| AC3 | `test_view_overrides_clear_category` | Set overrides on 3 categories, clear one → other two unchanged |
| AC4 | `test_view_overrides_clear_search` | Set force_vis on 5 blocks, clear → all force_vis is None |
| AC5 | `test_view_overrides_serialization` | `to_dict()` → `from_dict()` round-trip preserves all state |
| AC6 | `test_blocks_not_mutated_by_render` | `render_turn_to_strips()` → no block in tree has new attributes or changed field values vs snapshot taken before render |

### Existing Test Suites (must pass unchanged through Phase 2)

| # | Suite | Covers |
|---|---|---|
| AC7 | `test_gutter_rendering.py` | Arrow icons, expandable detection |
| AC8 | `test_xml_collapse.py` | Region expand/collapse, strip range |
| AC9 | `test_tool_rendering.py` | Tool summary collapse, force_vis |
| AC10 | `test_hot_reload.py` | State preservation across reload |
| AC11 | `test_search.py` | Search match finding |
| AC12 | `test_textual_visibility.py` | Visibility cycling |

### Full Suite

| # | Check | Command |
|---|---|---|
| AC13 | All tests pass | `uv run pytest` |
| AC14 | Lint clean | `just lint` |

## 6. Risks and Rollback

| Risk | Severity | Mitigation | Rollback |
|---|---|---|---|
| Cache key change (`id(block)` → `block_id`) invalidates block_strip_cache entries | Low — one-time miss per block, LRU refills | block_id is more stable (survives hot-reload, immune to GC) | Revert cache key lines (2 locations) |
| ViewOverrides auto-creates on miss — memory for blocks never clicked/searched | Negligible — dict entries are tiny, and get_block only called for blocks actually touched | `_blocks` dict grows only on access, not pre-populated | N/A |
| Region renderers signature change breaks `_REGION_PART_RENDERERS` dispatch | Medium — function signature mismatch | Phase 2 adds optional parameter with default None; Phase 3 makes required | Revert renderer signatures |
| Hot-reload: ViewOverrides serialization loses `force_vis` (complex VisState) | Low — search state is transient; cleared on reload anyway | `clear_search()` in restore path; don't serialize force_vis | `_force_vis` is already lost on reload today (monkey-patched attr) |
| Tests that directly set `block.expanded = True` break in Phase 3 | Medium — ~15 test locations | Update tests in Step 3.6 before removing fields | Phase 3 is atomic — revert to Phase 2 (fields still exist) |

**Rollback strategy per phase:**
- **Phase 1:** Delete `view_overrides.py`, remove `block_id` field. Pure deletion.
- **Phase 2:** Remove `overrides` parameter from all functions, revert to block-field reads/writes. Dual-write ensures blocks still have correct state.
- **Phase 3:** Restore `expanded`/`_strip_range` fields to FormattedBlock/ContentRegion. Phase 2 dual-writes make this immediately functional.

## 7. Parallelizable Beads Subtasks

```
cc-dump-6pv
│
├─ 6pv-A: Add block_id to FormattedBlock              ← Phase 1.1
│   deps: none
│   files: formatting.py
│   verify: AC1, AC2, AC13
│
├─ 6pv-B: Create ViewOverrides data structure          ← Phase 1.2
│   deps: none (uses formatting types only)
│   files: tui/view_overrides.py (new), tests/test_view_overrides.py (new)
│   verify: AC3, AC4, AC5
│
│   ┌──────────── 6pv-A and 6pv-B can run in PARALLEL ─────────────┐
│
├─ 6pv-C: Wire ViewOverrides into ConversationView     ← Phase 1.3
│   deps: 6pv-B
│   files: tui/widget_factory.py
│   verify: AC13 (hot-reload tests pass)
│
├─ 6pv-D: Migrate rendering.py (dual-read/write)       ← Phase 2.1–2.4
│   deps: 6pv-A, 6pv-C
│   files: tui/rendering.py
│   verify: AC6, AC7, AC8, AC9, AC13
│
├─ 6pv-E: Migrate consumers (dual-read/write)          ← Phase 2.5–2.7
│   deps: 6pv-D
│   files: tui/widget_factory.py, tui/search_controller.py, tui/action_handlers.py
│   verify: AC10, AC11, AC12, AC13
│
└─ 6pv-F: Remove view fields from FormattedBlock       ← Phase 3
    deps: 6pv-E
    files: formatting.py, tui/rendering.py, tui/widget_factory.py,
           tui/search_controller.py, tui/action_handlers.py,
           tests/test_hot_reload.py, tests/test_xml_collapse.py,
           tests/test_tool_rendering.py
    verify: ALL (AC1–AC14)
```

**Dependency DAG:**
```
6pv-A ─────┐
           ├─→ 6pv-D ─→ 6pv-E ─→ 6pv-F
6pv-B ─→ 6pv-C ─┘
```

**Max parallelism:** 2 (A ∥ B at start)

## 8. Execution Checklist

- [ ] Confirm cc-dump-yj3 blocker is closed (✅ ff55efb)
- [ ] **6pv-A:** Add `block_id` to FormattedBlock → `uv run pytest`
- [ ] **6pv-B:** Create `view_overrides.py` + `test_view_overrides.py` → `uv run pytest tests/test_view_overrides.py`
- [ ] **6pv-C:** Wire into ConversationView + hot-reload → `uv run pytest tests/test_hot_reload.py`
- [ ] **6pv-D:** Migrate rendering.py (dual-read + cache key change) → `uv run pytest tests/test_gutter_rendering.py tests/test_xml_collapse.py tests/test_tool_rendering.py`
- [ ] **6pv-E:** Migrate widget_factory + search_controller + action_handlers → `uv run pytest`
- [ ] **6pv-F:** Remove old fields + update tests → `uv run pytest && just lint`
- [ ] Write AC6 invariant test (blocks not mutated by render)
- [ ] Final full suite: `uv run pytest` clean, `just lint` clean
- [ ] Commit per subtask with `[6pv-X]` prefix

---

**FINAL PLAN**
