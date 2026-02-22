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

**View store** (`view_store.py`): HotReloadStore holding all interactive view state — category visibility (`vis:*`, `full:*`, `exp:*`), panel open/close (`panel:settings`, `panel:side_channel`, `panel:launch_config`), active panel, follow mode, and side channel state. `active_filters` is a `Computed` that derives `VisState` from the store keys.

**Derived reactions** (`view_store.py`): `footer_state`, `error_items`, and `sc_panel_state` are `Computed` values. Four `reaction()` registrations in `setup_reactions()` automatically push state to widgets — no manual `_update_*()` call sites.

**Input mode** (`app.py`): `_input_mode` is a property that derives from view store booleans + search state. No separate boolean tracking.

**Domain data** (`widget_factory.py`): `ConversationView` owns a list of `TurnData` objects. Each `TurnData` holds `FormattedBlock` lists and pre-rendered `Strip` arrays. Blocks arrive via `event_handlers.py` and are appended to the current turn.

**View state on domain objects**: `FormattedBlock.expanded` (per-block override, `formatting.py`) and `block._expandable` (set by renderer, `rendering.py`) are view state still living on domain objects.

**Search state** (`search.py`): `SearchState` is a plain dataclass with its own phase machine, saved filter snapshots, debounce timers, and match lists. Not yet integrated into the reactive graph.

### What's been solved (Phases 1-4)

1. **Category visibility** — Three Textual `reactive` dicts replaced by flat SnarfX store keys. Single `autorun` re-render instead of three watchers. Batched updates.

2. **Panel/follow state** — Scattered app booleans (`_settings_panel_open`, etc.) replaced by store keys. `_input_mode` derived from store state, not manually tracked.

3. **Derived push functions** — `_update_footer_state()` (15 call sites), `_update_error_indicator()` (3 call sites), `_update_side_channel_panel_display()` (5 call sites) all eliminated. Replaced by `Computed` + `reaction()` that fire automatically on state change.

### What's still wrong

1. **`block.expanded` contaminates domain objects** — Per-block expansion overrides sit on `FormattedBlock`. This means domain objects are mutated after creation, expansion state is lost on hot-reload, and `clear_overrides()` must walk all blocks. Fix: Phase 5 (move to view store).

2. **`block._expandable` is a render side effect on a domain object** — Set during rendering (`rendering.py:2082`), read by click handler. Acceptable interim coupling — becomes a render output (not stored on block) in Phase 8.

3. **Search state doesn't survive hot-reload** — `SearchState` is a plain dataclass on the app. File save mid-search loses query, phase, and mode settings. Fix: Phase 6 (identity state to view store, matches recomputed).

4. **No domain store abstraction** — Turn data is a list on `ConversationView`. No way to observe "new turn appended" reactively. Event handlers reach through `widgets["conv"]`. Fix: Phase 7.

5. **Render invalidation has two paths** — New data arrival (`_handle_event_inner`) and user toggles take different code paths to `conv.rerender()`. Fix: Phase 8 (unified computed pipeline). Tightly coupled with Phase 7 — domain store provides the observable input.

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
|                  |     | ✅ Core DONE     |     | Survives reload  |
|                  |     | Survives reload  |     | Reset on restart |
|                  |     | Reset on restart |     |                  |
+--------+---------+     +--------+---------+     +--------+---------+
         |                         |                        |
         +------------+------------+------------------------+
                      |
                      v
         +---------------------------+
         | Computed / Derived Layer  |
         |                          |
         | active_filters           |  ✅ Computed from vis/full/exp keys
         | input_mode               |  ✅ Derived from panel + search state
         | footer_state             |  ✅ Computed from filters + panels + tmux
         | error_items              |  ✅ Computed from exceptions + stale files
         | side_channel_panel_state |  ✅ Computed from sc fields
         | expandable_map           |  Render output (Phase 8), not stored on blocks
         | visible_blocks           |  Computed from domain + active_filters
         | tool_collapse            |  Computed from consecutive tool blocks
         | rendered_strips          |  Computed from visible + expanded + theme
         +-------------+------------+
                       |
                       v
         +---------------------------+
         | Reactions (side effects)  |
         |                          |
         | → persist settings       |  ✅ settings_store → disk
         | → sync consumers         |  ✅ settings_store → tmux, side_channel
         | → refresh viewport       |  ✅ any render input → conv.refresh()
         | → update footer widget   |  ✅ footer_state → StatusFooter
         | → update error overlay   |  ✅ error_items → ConversationView
         | → update panel widgets   |  ✅ panel state → panel display
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

### What This Buys Us (Phases 1-4 realized, 5-8 projected)

**Predictable invalidation.** ✅ When the user presses `3` to cycle tools visibility:

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

**Trivial streaming.** (Phase 7-8) New event arrives:

```
domain_store.append_block(new_block)
  → rendered_strips Computed appends one resolved block (previous blocks unchanged, memo hit)
    → render reaction calls conv.refresh()
```

Append-only domain data means previous derivations are always valid.

**Elimination of manual push calls.** ✅ `_update_footer_state()` (15 call sites), `_update_error_indicator()` (3 call sites), `_update_side_channel_panel_display()` (5 call sites) — all eliminated and replaced with `reaction()` registrations. Zero manual push calls remain.

**Hot-reload simplification.** (Partially realized) View state now survives hot-reload via HotReloadStore. Reactions re-register via `reconcile()`. Full simplification (Phase 8) will eliminate the state capture/restore dance for widget replacement entirely.

**Undo/debug for free.** (Phase 7-8) View state is a plain object — snapshot it, restore it, time-travel through it. Domain data is an immutable log — replay from any point.

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

| Before | After | Status |
|---|---|---|
| `_is_visible = reactive({})` | `store.get("vis:tools")` | ✅ |
| `_is_full = reactive({})` | `store.get("full:tools")` | ✅ |
| `_is_expanded = reactive({})` | `store.get("exp:tools")` | ✅ |
| `active_panel = reactive("session")` | `store.get("panel:active")` | ✅ |
| `show_logs = reactive(False)` | keep as Textual reactive (drives CSS `display`) | ✅ kept |
| `show_info = reactive(False)` | keep as Textual reactive (drives CSS `display`) | ✅ kept |
| `conv._follow_state` | `store.get("follow")` | ✅ |
| `block.expanded` | `expansion_overrides[block_id]` | Phase 5 |
| `_settings_panel_open` | `store.get("panel:settings")` | ✅ |
| `_side_channel_panel_open` | `store.get("panel:side_channel")` | ✅ |
| `_launch_config_panel_open` | `store.get("panel:launch_config")` | ✅ |
| `_search_state.phase` | `store.get("search:phase")` | Phase 6 |
| `_search_state.query` | `store.get("search:query")` | Phase 6 |
| `_active_filterset_slot` | `store.get("active_filterset")` | ✅ |
| `_input_mode` (property) | derived from store + search state | ✅ |
| `_update_footer_state()` (15 call sites) | `reaction` on footer_state Computed | ✅ |
| `_update_error_indicator()` (3 call sites) | `reaction` on error_items Computed | ✅ |
| `_update_side_channel_panel_display()` (5 call sites) | `reaction` on sc_panel_state Computed | ✅ |

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

### Phase 2: View Store — Category Visibility ✅ (done)

Replaced `_is_visible`/`_is_full`/`_is_expanded` Textual reactives with a SnarfX HotReloadStore in `view_store.py`. `active_filters` is a `Computed`. Single `autorun` for re-render instead of three `watch__is_*` methods. Action handlers write to store keys instead of dict-copy. Commit `265784b`.

### Phase 3: View Store — Panel, Follow, & Input Mode ✅ (done)

Moved `active_panel`, `_follow_state`, panel open/close booleans into the view store. `_input_mode` is a property derived from store state + search phase. Old Textual reactives and scattered booleans removed from `app.py`. Commit `db998c1`.

### Phase 4: Derived Reactions — Footer, Error, Side Channel ✅ (done)

Eliminated all manual `_update_*()` push functions. `footer_state`, `error_items`, and `sc_panel_state` are `Computed` values in `view_store.py`. Four `reaction()` registrations auto-push to widgets. `_update_footer_state()` (15 call sites), `_update_error_indicator()` (3 call sites), `_update_side_channel_panel_display()` (5 call sites) all removed. Follow-up commit `b13eb12` cleaned up function-level imports across 17 files. Commits `82be2fb`, `b13eb12`.

---

### Intermission: Lessons from Phases 1-4

Before continuing, three structural problems accumulated across Phases 1-4 that should be addressed now — before the foundation gets deeper.

#### Lesson A: The widget-push guard is copy-pasted, not enforced

Every reaction that touches a Textual widget needs `if not app.is_running or app._replacing_widgets: return` to avoid crashes during hot-reload widget swap or before the app is mounted. This guard appears 5 times: once in `_rerender_if_mounted` (`app.py:454`), and four times in `view_store.py` push functions (`_on_active_panel_changed`, `_push_footer`, `_push_error_items`, `_push_sc_panel`). Phase 5 will add more push targets. Phase 6 will add search bar updates. Each one will need the same guard, and forgetting it will cause a crash that only manifests during hot-reload.

**Work**: Extract a `_guarded_push(app, fn)` helper (or decorator) that encapsulates the guard. All existing push functions and `_rerender_if_mounted` use it. Future phases get the guard for free. Single enforcer for the "is it safe to touch widgets?" invariant.

#### Lesson B: The view store schema grew across three phases with inconsistent naming

`settings_store.py` has 3 keys, defined all at once. `view_store.py` has 32 keys that were added across Phases 2, 3, and 4, resulting in mixed naming conventions:
- Namespaced with colons: `vis:user`, `panel:active`, `sc:loading`, `tmux:available`
- Bare names: `follow`, `active_filterset`, `active_launch_config_name`, `theme_generation`

The bare names were added as one-offs in later phases without revisiting the convention. `active_filterset` should probably be `filter:active_set`. `active_launch_config_name` should probably be `launch:active_name`. `theme_generation` should probably be `theme:generation`. `follow` should probably be `nav:follow`.

**Work**: Normalize the schema key names to use consistent `namespace:key` convention. This is a rename — find all `store.get("x")` and `store.set("x", ...)` call sites and update them. Do it now while there are ~32 keys and the call sites are known. After Phases 5-6 add more keys, this gets harder.

#### Lesson C: The view store has high fan-out — it imports 5 widget modules

`settings_store.py` imports one module (`settings` — disk I/O). `view_store.py` imports `formatting`, `widget_factory`, `error_indicator`, `side_channel_panel`, `custom_footer`, and `action_handlers`. The store knows about every widget it pushes to. Each phase bolted on another import.

Phase 1's `setup_reactions(store, context)` pointed toward a better pattern: the store doesn't know about consumers — consumers are provided via `context`. But Phase 4 went the other way: `view_store.py` hardcodes `import cc_dump.tui.side_channel_panel` so it can construct `SideChannelPanelState` and query `app.screen.query(SideChannelPanel)`.

**Work**: Push functions move out of `view_store.py`. The store defines schema + computeds. `setup_reactions` accepts push functions via the `context` dict (same pattern `settings_store.py` uses for `side_channel_manager` and `tmux_controller`). Each widget module — or a single `reactions.py` bridge module — owns its push function. `view_store.py` drops to 1-2 imports (formatting, category_config) and stays a pure data module.

---

### Phase 5: Move Block Expansion Overrides to View Store

**Goal**: `FormattedBlock.expanded` stops being stored on domain objects. Expansion overrides live in the view store. Hot-reload preserves expansion state.

**Why split from `_expandable`**: `_expandable` is determined *during* rendering — it depends on whether a different expanded renderer exists, whether strips exceed the truncation limit, and whether the block has children. These are all rendering outputs, not store inputs. `_expandable` becomes derived in Phase 8 when the render pipeline is computed. `block.expanded` (the user's click override) is pure view state and belongs in the store now.

**Files to change**:
- `formatting.py`: Remove `expanded` field from `FormattedBlock`
- `view_store.py`: Add `ObservableDict` for per-block expansion overrides, keyed by block identity
- `widget_factory.py` click handler: Writes to view store expansion dict instead of `block.expanded`
- `action_handlers.py:clear_overrides()`: Clears view store expansion dict entries instead of walking blocks
- `rendering.py`: `resolve_visibility()` reads expansion override from view store instead of `block.expanded`
- `search_controller.py`: Search block expansion writes to view store expansion dict

**`_expandable` stays as render-time annotation** until Phase 8. It's a rendering output, not state — the block just carries the flag between render and click-handler. Acceptable interim coupling.

**Verification**: Click-to-expand works. Hot-reload preserves expansion state. Expansion overrides cleared on category cycle. Search expand/restore works.

### Phase 6: Search State in View Store

**Goal**: Search identity state survives hot-reload. User doesn't lose their search mid-session when a file changes.

**What goes in the store** (identity state — survives reload):
- `search:phase` — INACTIVE / EDITING / NAVIGATING
- `search:query` — the search string
- `search:modes` — mode flags (case, word, regex, incremental)
- `search:current_index` — position in match list
- `search:saved_filters` — filter snapshot for restore-on-cancel (already reads/writes view store keys; this becomes a snapshot dict)

**What stays transient** (derived or ephemeral — recomputed after reload):
- `matches` list — recomputed from (turns, pattern) after reload
- `cursor_pos` — resets to end-of-query on reload (acceptable)
- `debounce_timer` — execution scheduling, not state
- `expanded_blocks` — tracking list for undo; recomputable from expansion overrides (Phase 5)
- `saved_scroll_y` — acceptable to lose on reload

**Files to change**:
- `view_store.py`: Add search keys to schema.
- `search.py`: `SearchState` reads identity fields from view store. Transient fields stay on the dataclass. `SearchBar.update_display()` reads from store.
- `search_controller.py`: Mutations write to store. After hot-reload reconcile, a reaction recomputes matches from stored query + turns.

**Verification**: Search works identically. Hot-reload preserves search query, phase, and modes. Matches recompute automatically after reload.

### Phase 7+8: Domain Store & Unified Render Pipeline

> **Why combined**: A domain store (ObservableList) without a unified render pipeline just adds abstraction without simplifying anything — event handlers would write to the store, but the two render paths (`_handle_event_inner` vs `_rerender_if_mounted`) would still exist. The value comes from the combination: domain store provides the observable input, computed render pipeline provides the single invalidation path. Plan as tightly sequenced or combined.

#### Phase 7: Domain Store

**Goal**: Formalize turn data as an `ObservableList` owned by a domain store. Event handlers write to domain store instead of reaching through widget refs.

**Files to change**:
- New: `src/cc_dump/domain_store.py` (RELOADABLE)
- `widget_factory.py`: `ConversationView._turns` becomes a reference to `domain_store.turns`
- `event_handlers.py`: Receives domain store instead of `widgets["conv"]`. Appends blocks to domain store.
- `app.py`: Creates domain store, passes to event handlers and ConversationView
- `cli.py`: Creates domain store

**Verification**: Replay mode works (append-only). Live proxy works. Turn sealing works. Hot-reload preserves accumulated turns.

#### Phase 8: Unified Render Pipeline + Derived Expandability

**Goal**: Single render invalidation path. Both "new data" and "user toggle" flow through the same derived → render pipeline. `_expandable` becomes a rendering output, not a mutation on domain objects.

**Files to change**:
- New or in `view_store.py`: `Computed` chain: domain turns → tool collapse → visibility resolution → strip rendering
- `widget_factory.py`: `render_line(y)` reads from computed strips instead of maintaining its own `_turns` list. `rerender()` method eliminated — refresh is just reading fresh Computed values.
- `app.py`: Remove `_handle_event_inner` render path vs `_rerender_if_mounted` path — both become a single `autorun` that calls `conv.refresh()`.
- `rendering.py`: `_expandable` returned alongside strips as part of the computed render output, not set on `block._expandable`. Click handler reads expandability from the render result.
- `widget_factory.py`: `_is_expandable_block` reads from render output instead of `getattr(block, "_expandable")`.

**Hot-reload simplification**: Widget replacement reduces to: remove old widgets, mount fresh ones. New widgets read from the same stores. No state capture/restore dance needed.

**Verification**: Single code path for all re-renders. Profiling confirms memoization prevents unnecessary recomputation. `_expandable` no longer stored on blocks.

## Design Decisions

### Why HotReloadStore for view state?

View store reconcile preserves visibility, panel, and follow state across hot-reload. Before Phases 2-4, hot-reload + widget replacement would reset `_follow_state` and lose per-block expansion. Now the data survives and reactions re-register via `reconcile()`. This is proven in production.

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
