# State Management Roadmap

cc-dump uses SnarfX (MobX-inspired reactive primitives) for state management. The settings store (`settings_store.py`) is the first SnarfX-backed store in production. This document describes the full target architecture and how to get there.

## The Two Orthogonal State Dimensions

The system has two independent inputs:

1. **Domain Data** (append-only, from proxy) — events and FormattedBlocks arriving via the proxy. Immutable once received. Only grows, never mutates.

2. **View State** (interactive, from user) — how the user wants to see the data. Visibility levels, per-block expansion, active panel, follow mode, scroll position, search query, open panels.

Rendered output is a pure function of both: `render(domainData, viewState) -> UI`

Neither input needs to know about the other.

## Current State

### What exists today

**SnarfX primitives** (`snarfx/`): Observable, ObservableList, ObservableDict, Computed, Store, HotReloadStore. All state lives in `_anchor.py` (plain dicts) so behavior modules can be reloaded while data persists.

**Settings store** (`settings_store.py`): HotReloadStore with schema, disk persistence reaction, consumer sync reactions (tmux, side channel). Hot-reload reconciles schema + reactions automatically.

**Visibility state** (`app.py:83-85`): Three Textual `reactive` dicts (`_is_visible`, `_is_full`, `_is_expanded`) — the sole source for category visibility. `active_filters` property derives `VisState` from them. Watchers trigger `_rerender_if_mounted()`.

**Domain data** (`widget_factory.py`): `ConversationView` owns a list of `TurnData` objects. Each `TurnData` holds `FormattedBlock` lists and pre-rendered `Strip` arrays. Blocks arrive via `event_handlers.py` and are appended to the current turn.

**View state on domain objects**: `FormattedBlock.expanded` (per-block override, `formatting.py:180`) and `block._expandable` (set by renderer, `rendering.py:2097`) are view state living on domain objects.

**Scattered app-level state** (`app.py:__init__`): Booleans for panel open/close (`_settings_panel_open`, `_launch_config_panel_open`, `_side_channel_panel_open`), side channel loading/result state (5 fields), exception tracking (`_exception_items`), active filterset slot, search state. All manually synchronized.

**Manual push functions**: `_update_footer_state()` is called from ~15 sites. `_update_side_channel_panel_display()` from ~5 sites. `_update_error_indicator()` from ~3 sites. Each manually assembles a state snapshot and pushes it to a widget. These are derived state that should be computed automatically.

### What's wrong

1. **Visibility state uses Textual reactives instead of SnarfX** — Three separate `reactive` dicts that must be updated in lockstep. Every mutation creates a new dict copy (`{**app._is_visible, category: val}`). No batching across the three axes.

2. **View state contaminates domain objects** — `expanded` and `_expandable` sit on `FormattedBlock`. This means domain objects are mutated after creation, blocks can't be shared or cached safely, and the block's expansion state is lost on hot-reload (widget replacement clears `_expandable`).

3. **No domain store abstraction** — Turn data is a list on `ConversationView`. There's no way to observe "new turn appended" reactively. Event handlers reach through `widgets["conv"]` to mutate turns.

4. **Render invalidation has two paths** — New data arrival (`_handle_event_inner`) and user toggles (`watch__is_visible` etc.) take different code paths to trigger re-render. Both ultimately call `conv.rerender()` but with different state assembly.

5. **Derived state is pushed, not pulled** — Footer state, error indicator state, side channel panel state, and input mode are all assembled manually and pushed to widgets from scattered call sites. These are pure functions of other state — they should be `Computed` values or `autorun` reactions that update automatically.

6. **Search state is a separate world** — `SearchState` has its own phase machine, saved filter snapshots, debounce timers, and match lists. It saves/restores visibility state independently. It should participate in the same reactive graph.

## Target Architecture

### The Stores

```
+------------------+     +------------------+     +------------------+
| Settings Store   |     | View Store       |     | Domain Store     |
| (HotReloadStore) |     | (HotReloadStore) |     | (ObservableList) |
|                  |     |                  |     |                  |
| claude_command   |     | vis:user         |     | turns[]          |
| auto_zoom_default|     | vis:tools        |     |   blocks[]       |
| side_channel_    |     | full:assistant   |     |   strips[]       |
|   enabled        |     | exp:system       |     |                  |
| theme            |     | follow_mode      |     | append-only      |
|                  |     | active_panel     |     | immutable entries |
| Persists to disk |     | active_filterset |     | rebuilt from HAR  |
| Survives restart |     | search_query     |     |                  |
|                  |     | search_phase     |     |                  |
| ✅ DONE          |     | panel:settings   |     |                  |
|                  |     | panel:side_chan   |     |                  |
|                  |     | expansion_       |     |                  |
|                  |     |   overrides{}    |     |                  |
|                  |     |                  |     |                  |
|                  |     | Survives reload  |     | Survives reload  |
|                  |     | Reset on restart |     | Reset on restart |
+--------+---------+     +--------+---------+     +--------+---------+
         |                         |                        |
         +------------+------------+------------------------+
                      |
                      v
         +---------------------------+
         | Computed / Derived Layer  |
         |                          |
         | active_filters           |  Computed from vis/full/exp keys
         | input_mode               |  Computed from panel + search state
         | footer_state             |  Computed from filters + panels + tmux
         | error_items              |  Computed from exceptions + stale files
         | side_channel_panel_state |  Computed from sc fields
         | expandable_map           |  Computed from blocks + levels + limits
         | visible_blocks           |  Computed from domain + active_filters
         | tool_collapse            |  Computed from consecutive tool blocks
         | rendered_strips          |  Computed from visible + expanded + theme
         +-------------+------------+
                       |
                       v
         +---------------------------+
         | Reactions (side effects)  |
         |                          |
         | → persist settings       |  settings_store → disk
         | → sync consumers         |  settings_store → tmux, side_channel
         | → refresh viewport       |  any render input → conv.refresh()
         | → update footer widget   |  footer_state → StatusFooter
         | → update error overlay   |  error_items → ConversationView
         | → update panel widgets   |  panel state → panel display
         +-------------+------------+
                       |
                       v
         +---------------------------+
         | Textual Widgets           |
         | (thin display shells)     |
         |                          |
         | ConversationView          |  render_line(y) reads from strips
         | StatusFooter              |  displays footer_state
         | SettingsPanel             |  reads/writes settings_store
         | StatsPanel, etc.          |  displays computed analytics
         +---------------------------+
```

### What This Buys Us

**Predictable invalidation.** When the user presses `3` to cycle tools visibility:

```
view_store.set("vis:tools", next_level)
  → active_filters Computed recomputes (only tools entry changes, memo cache hit on others)
    → visible_blocks Computed recomputes (only tools blocks re-resolve)
      → rendered_strips Computed recomputes (only affected turns)
        → render reaction calls conv.refresh()
  → footer_state Computed recomputes (picks up new vis:tools)
    → footer reaction pushes new display
```

No imperative "clear overrides, re-render all turns, update footer, update search bar" chain. The derivation graph handles it.

**Trivial streaming.** New event arrives:

```
domain_store.append_block(new_block)
  → rendered_strips Computed appends one resolved block (previous blocks unchanged, memo hit)
    → render reaction calls conv.refresh()
```

Append-only domain data means previous derivations are always valid.

**Elimination of manual push calls.** `_update_footer_state()` called from 15 sites becomes a single `autorun`. `_update_error_indicator()` from 3 sites becomes a single `autorun`. `_update_side_channel_panel_display()` from 5 sites becomes a single `autorun`. No more forgetting to call the update function after a state change.

**Hot-reload simplification.** Widget replacement (`hot_reload_controller.py`) currently does state capture → widget removal → widget creation → state restoration → re-render. With SnarfX stores, widget replacement just removes old widgets and mounts fresh ones. State lives in stores (survives). Reactions re-register via `reconcile()`. The new widgets read from the same stores.

**Undo/debug for free.** View state is a plain object — snapshot it, restore it, time-travel through it. Domain data is an immutable log — replay from any point.

### Design Challenges

**Streaming turns.** A turn is either in-progress (blocks still arriving) or sealed. The domain store needs this concept so the derived layer knows whether to re-derive on every append or wait for the turn to seal.

**Tool collapse as derivation.** `collapse_tool_runs()` creates `ToolUseSummaryBlock` from consecutive tool use/result pairs. This is a domain-level transformation that creates new blocks from existing ones. It should live as a Computed between the raw domain store and the visibility resolver — not as a mutation of the domain store. One place decides whether to collapse (single enforcer).

**Virtualized rendering.** With thousands of turns, only the viewport is rendered. The derived layer produces a virtual list — total height plus a function `renderRange(startLine, endLine)`. Scroll position (view state) determines which range to materialize. A naive Computed over all turns won't scale — the strip cache needs to be incremental (append-only, matching the domain store).

**Search integration.** Search currently saves/restores filter state, expands matched blocks, and has its own debounce timer. In the target: search query and phase live in the view store. Search results are a Computed over (domain blocks, query, modes). Matched block expansion is just entries in the expansion overrides dict. Saving/restoring filters is a snapshot/restore of view store keys. The debounce timer stays as a transient (not in a store — it's execution scheduling, not state).

**Textual bridge.** SnarfX reactions run synchronously on `set()`. Textual expects mutations from the main thread. The bridge: reactions that touch widgets use `app.call_from_thread()` (same pattern as the current settings store consumer sync). For state that drives Textual CSS (`display` property on panels), keep using Textual's system — SnarfX reactions set widget properties, Textual handles CSS revalidation.

## Target Architecture — Detail

### Settings Store ✅ (done)

`HotReloadStore` in `settings_store.py`. Schema-defined keys, persistence reaction, consumer sync reactions.

```python
# Already implemented
store = cc_dump.settings_store.create()
store.get("theme")          # reactive read
store.set("theme", "dark")  # triggers persistence + any watchers
```

### View Store — User Interaction State

A `HotReloadStore` replacing the three Textual `reactive` dicts, panel booleans, follow state, search scalars, and active filterset.

**Schema** (flat, small, fast to diff):

```python
# view_store.py (RELOADABLE)
SCHEMA = {
    # Category visibility — one Observable per category per axis
    "vis:user": True,       "full:user": True,       "exp:user": False,
    "vis:assistant": True,   "full:assistant": True,   "exp:assistant": False,
    "vis:tools": True,       "full:tools": False,      "exp:tools": False,
    "vis:system": False,     "full:system": False,     "exp:system": False,
    "vis:metadata": False,   "full:metadata": False,   "exp:metadata": False,
    "vis:thinking": False,   "full:thinking": False,   "exp:thinking": False,
    # ... (derived from CATEGORY_CONFIG defaults)

    # Navigation
    "follow_mode": "active",    # "active" | "paused" | "off"
    "active_panel": "session",
    "active_filterset": None,

    # Panel open/close
    "panel:settings": False,
    "panel:side_channel": False,
    "panel:launch_config": False,
    "panel:keys": False,

    # Search scalars (matches/timer are transient, not stored)
    "search:phase": "inactive",  # "inactive" | "editing" | "navigating"
    "search:query": "",
    "search:cursor_pos": 0,
}
```

**Per-block expansion** — an `ObservableDict[str, bool]` keyed by block ID, owned by the view store (not on the store schema since it's a collection, not a scalar). Replaces `FormattedBlock.expanded`.

**Derived state** — all become `Computed`:

```python
active_filters = Computed(...)     # VisState dict from vis/full/exp keys
input_mode = Computed(...)         # from panel + search state
footer_state = Computed(...)       # from filters + panels + tmux + follow
error_items = Computed(...)        # from _exception_items + stale_files
```

**Migration from Textual reactives and app booleans**:

| Today (`app.py`) | Target (`view_store.py`) |
|---|---|
| `_is_visible = reactive({})` | `store.get("vis:tools")` |
| `_is_full = reactive({})` | `store.get("full:tools")` |
| `_is_expanded = reactive({})` | `store.get("exp:tools")` |
| `active_panel = reactive("session")` | `store.get("active_panel")` |
| `show_logs = reactive(False)` | keep as Textual reactive (drives CSS `display`) |
| `show_info = reactive(False)` | keep as Textual reactive (drives CSS `display`) |
| `conv._follow_state` | `store.get("follow_mode")` |
| `block.expanded` | `expansion_overrides[block_id]` |
| `_settings_panel_open` | `store.get("panel:settings")` |
| `_side_channel_panel_open` | `store.get("panel:side_channel")` |
| `_launch_config_panel_open` | `store.get("panel:launch_config")` |
| `_search_state.phase` | `store.get("search:phase")` |
| `_search_state.query` | `store.get("search:query")` |
| `_active_filterset_slot` | `store.get("active_filterset")` |
| `_input_mode` (property) | `Computed` from panel + search state |
| `_update_footer_state()` (15 call sites) | `autorun` on footer_state Computed |
| `_update_error_indicator()` (3 call sites) | `autorun` on error_items Computed |
| `_update_side_channel_panel_display()` (5 call sites) | `autorun` on sc state Computed |

### Domain Store — Append-Only Event Log

An `ObservableList[TurnData]` replacing the plain list on `ConversationView`. Not a `Store` subclass — it's a single `ObservableList` with domain-specific methods.

```python
# domain_store.py (RELOADABLE)
class DomainStore:
    """Append-only event log. Owns all FormattedBlocks."""

    def __init__(self):
        self.turns = ObservableList()   # ObservableList[TurnData]
        self._open_turn: TurnData | None = None

    def append_block(self, block: FormattedBlock, filters: dict) -> None:
        """Append a block to the current turn (or start a new one)."""
        ...

    def seal_turn(self) -> None:
        """Mark the current turn as complete."""
        ...
```

**Migration**:

| Today (`widget_factory.py`) | Target (`domain_store.py`) |
|---|---|
| `self._turns: list[TurnData]` | `domain_store.turns: ObservableList[TurnData]` |
| `self._current_turn: TurnData` | `domain_store._open_turn` |
| `event_handlers.py` mutates via `widgets["conv"]` | `event_handlers.py` appends to `domain_store` |

**Key property**: Domain data is immutable after creation. `FormattedBlock` objects are never mutated (expansion state moved to view store). `TurnData` strips are computed once and cached.

### Derived/Computed Layer

Pure `Computed` values that combine stores:

```python
# Expandability is derived, not stored on blocks
is_expandable = Computed(lambda: {
    block.id: _compute_expandable(block, view_store.get(f"full:{block.category}"))
    for turn in domain_store.turns
    for block in turn.blocks
})

# Tool collapse is a derivation, not a mutation
collapsed_turns = Computed(lambda: [
    collapse_tool_runs(turn, active_filters.get())
    for turn in domain_store.turns
])

# Visible blocks for current viewport
visible_blocks = Computed(lambda: [
    ResolvedBlock(block, active_filters.get().get(block.category))
    for turn in collapsed_turns.get()
    for block in turn.blocks
    if active_filters.get().get(block.category, HIDDEN).visible
])
```

**`_expandable` becomes derived**: Currently `rendering.py:2097` sets `block._expandable` as a side effect during rendering. In the target, expandability is a `Computed` over (block content, current level, truncation limits) — never stored on the block.

### The App as Thin Coordinator

In the target, `CcDumpApp` is almost empty:

- `compose()` — mounts widgets (unchanged)
- `on_key()` — reads `input_mode` Computed, dispatches to keymap (unchanged shape, simpler impl)
- `on_mount()` — creates reactions bridging SnarfX → Textual widgets
- No `_update_*` methods — all replaced by reactions
- No `watch__is_*` methods — all replaced by a single render autorun
- No scattered state booleans — all in view store

The app doesn't own state. It owns the Textual widget tree and the reactions that bridge SnarfX state into that widget tree.

## Data Flow

```
+---------------+     +---------------+     +------------------+
| Proxy/SSE     |     | User Input    |     | Disk (settings   |
| events from   |     | (keys,        |     |  .json)          |
| network       |     |  clicks)      |     |                  |
+-------+-------+     +-------+-------+     +--------+---------+
        |                      |                      |
        v                      v                      v
+---------------+     +---------------+     +------------------+
| Domain Store  |     | View Store    |     | Settings Store   |
| (append-only  |     | (visibility,  |     | (claude_command,  |
|  block log)   |     |  panels,      |     |  theme, etc.)    |
|               |     |  search,      |     |                  |
|               |     |  expansion)   |     | ✅ DONE          |
+-------+-------+     +-------+-------+     +--------+---------+
        |                      |                      |
        +----------+-----------+----------+-----------+
                   |                      |
                   v                      v
          +----------------+     +------------------+
          | Computed Layer |     | Reactions         |
          | (memoized,     |     | (side effects)    |
          |  lazy)         |     |                   |
          |                |     | → disk persist    |
          | active_filters |     | → consumer sync   |
          | visible_blocks |     | → widget refresh  |
          | footer_state   |     | → footer update   |
          | input_mode     |     | → error overlay   |
          | error_items    |     |                   |
          | expandable_map |     |                   |
          +--------+-------+     +------------------+
                   |
                   v
          +----------------+
          | Render Layer   |
          | (viewport only)|
          |                |
          | render_line(y) |
          | binary search  |
          | strip cache    |
          +----------------+
```

## Migration Order

Each phase is independently shippable and testable.

### Phase 1: Settings Store ✅ (done)

`settings_store.py` with HotReloadStore, persistence reaction, consumer sync. Proved the pattern works with hot-reload.

### Phase 2: View Store — Category Visibility

**Goal**: Replace `_is_visible`/`_is_full`/`_is_expanded` Textual reactives with a SnarfX HotReloadStore. Single `autorun` for re-render instead of three `watch__is_*` methods.

**Files to change**:
- New: `src/cc_dump/view_store.py` (RELOADABLE) — schema, reactions, `active_filters` Computed
- `app.py`: Remove three reactive dicts + watchers. Accept view store. `active_filters` reads from Computed.
- `action_handlers.py`: `toggle_vis`/`toggle_detail`/`toggle_expand`/`cycle_vis` write to view store instead of dict-copy
- `search_controller.py:29-31, 192-194`: Read/write view store instead of `app._is_visible` etc.
- `hot_reload_controller.py:150-152`: Same
- `cli.py`: Create view store, pass to app
- Add to `_RELOAD_ORDER` in `hot_reload.py`

**Verification**: All existing tests pass. `action_handlers` tests confirm batched updates. Manual: press category keys, verify single re-render per keypress (not three).

### Phase 3: View Store — Panel, Follow, & Input Mode

**Goal**: Move `active_panel`, `_follow_state`, panel open/close booleans into the view store. `_input_mode` becomes a `Computed`.

**Files to change**:
- `view_store.py`: Add panel/follow keys to schema. Add `input_mode` Computed.
- `app.py`: Remove `active_panel` reactive and `watch_active_panel`. Remove `_settings_panel_open`, `_launch_config_panel_open`, `_side_channel_panel_open` booleans. `_input_mode` property reads from Computed.
- `widget_factory.py`: `_follow_state` reads from view store.
- `action_handlers.py`: Panel cycling writes to view store.
- All panel open/close methods: Write to view store instead of setting app booleans.

**Verification**: Panel cycling, follow mode toggle, vim navigation all work. Hot-reload preserves panel and follow state.

### Phase 4: Derived Reactions — Footer, Error, Side Channel

**Goal**: Eliminate all manual `_update_*()` push functions. Replace with `autorun` reactions that fire when their input state changes.

**Files to change**:
- `view_store.py` (or `derived_reactions.py`): `footer_state` Computed, `error_items` Computed, `side_channel_panel_state` Computed. `autorun` reactions that push to widgets.
- `app.py`: Remove `_update_footer_state()` and all ~15 call sites. Remove `_update_error_indicator()` and all ~3 call sites. Remove `_update_side_channel_panel_display()` and all ~5 call sites. Remove `_side_channel_loading`, `_side_channel_result_text`, etc. — all move to view store.
- `hot_reload_controller.py`: Remove manual `_update_footer_state()` call after widget replacement — reaction handles it.

**Verification**: Footer updates automatically on any state change. Error indicator updates automatically. Side channel panel syncs automatically. No manual calls remain.

### Phase 5: Extract Block Expansion from Domain Objects

**Goal**: `FormattedBlock.expanded` and `block._expandable` stop being stored on blocks. Expansion overrides live in view store. Expandability is derived.

**Files to change**:
- `formatting.py:180`: Remove `expanded` field from `FormattedBlock`
- `view_store.py`: Add `ObservableDict` for per-block expansion overrides
- `rendering.py:2090-2097`: `_expandable` computed from (block, level, limits) instead of set as side effect
- `widget_factory.py:941-943, 1178`: `_is_expandable_block` reads derived expandability
- `widget_factory.py` click handler: Writes to view store expansion dict instead of `block.expanded`

**Verification**: Click-to-expand works. Hot-reload preserves expansion state. Expansion overrides cleared on category cycle (same behavior as today's `_clear_overrides`).

### Phase 6: Search State in View Store

**Goal**: Search query, phase, and modes live in the view store. Search results become a Computed. Saving/restoring filters becomes a view store snapshot.

**Files to change**:
- `view_store.py`: Add search keys to schema.
- `search.py`: `SearchState` becomes a thin accessor over view store keys. Matches list stays transient (derived, not stored).
- `search_controller.py`: Save/restore filters = snapshot/restore view store keys. Expand matched blocks = write to expansion overrides dict.

**Verification**: Search works identically. Hot-reload preserves search query and phase.

### Phase 7: Domain Store

**Goal**: Formalize turn data as an `ObservableList` owned by a domain store. Event handlers write to domain store instead of reaching through widget refs.

**Files to change**:
- New: `src/cc_dump/domain_store.py` (RELOADABLE)
- `widget_factory.py`: `ConversationView._turns` becomes a reference to `domain_store.turns`
- `event_handlers.py`: Receives domain store instead of `widgets["conv"]`. Appends blocks to domain store.
- `app.py`: Creates domain store, passes to event handlers and ConversationView
- `cli.py`: Creates domain store

**Verification**: Replay mode works (append-only). Live proxy works. Turn sealing works. Hot-reload preserves accumulated turns.

### Phase 8: Unified Render Pipeline

**Goal**: Single render invalidation path. Both "new data" and "user toggle" flow through the same derived → render pipeline.

**Files to change**:
- New or in `view_store.py`: `Computed` chain: domain turns → tool collapse → visibility resolution → strip rendering
- `widget_factory.py`: `render_line(y)` reads from computed strips instead of maintaining its own `_turns` list. `rerender()` method eliminated — refresh is just reading fresh Computed values.
- `app.py`: Remove `_handle_event_inner` render path vs `_rerender_if_mounted` path — both become a single `autorun` that calls `conv.refresh()`.

**Hot-reload simplification**: Widget replacement reduces to: remove old widgets, mount fresh ones. New widgets read from the same stores. No state capture/restore dance needed.

**Verification**: Single code path for all re-renders. Profiling confirms memoization prevents unnecessary recomputation.

## Design Decisions

### Why HotReloadStore for view state?

View store reconcile preserves visibility settings across hot-reload. Today, hot-reload + widget replacement resets `_follow_state` and loses per-block expansion. With a HotReloadStore, the data survives and reactions re-register.

### Why not put everything in one store?

Settings, view state, and domain data have different lifecycles:
- **Settings** persist to disk, survive app restarts
- **View state** survives hot-reload, reset on app restart
- **Domain data** survives hot-reload, rebuilt from HAR on replay

Different stores = different reconcile strategies, different persistence, independent testing.

### Why ObservableList for domain data instead of Store?

`Store` is for flat key-value schemas. Domain data is an ordered collection (turns) containing nested collections (blocks). `ObservableList` is the right primitive — it notifies on append, which is the only mutation.

### What about Textual's reactive system?

Textual reactives (`reactive[T]`) trigger CSS revalidation and watcher methods. SnarfX Observables don't. For state that drives CSS (widget visibility via `display`), keep using Textual's system. For state that drives our custom render pipeline (visibility filters, domain data), use SnarfX.

The bridge: a SnarfX `autorun` that calls `app.call_from_thread()` or `conv.refresh()` when SnarfX state changes. SnarfX owns the data; Textual owns the display.

### Settings persistence vs view state

Settings are the persisted subset of view state. They load on startup to seed the settings store. They save on change via a persistence reaction. Settings are not a separate state system — they're serialization of one store's state. View state (visibility, panels, follow mode) does not persist to disk.
