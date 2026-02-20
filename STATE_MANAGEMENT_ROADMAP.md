# State Management Roadmap

cc-dump currently has no intentional state management. State is scattered across reactives, dicts, and widget attributes with ad-hoc synchronization. This document describes the target architecture.

## The Two Orthogonal State Dimensions

The system has two independent inputs:

1. **Domain Data** (append-only, from proxy) — events and FormattedBlocks arriving via the proxy. Immutable once received. Only grows, never mutates.

2. **View State** (interactive, from user) — how the user wants to see the data. Visibility levels, per-block expansion, active panel, follow mode, scroll position.

Rendered output is a pure function of both: `render(domainData, viewState) -> UI`

Neither input needs to know about the other.

## The Three Stores

### 1. Domain Store — Append-Only Event Log

The proxy pushes events. The client appends FormattedBlocks to an ordered collection. **Never mutated after arrival.**

This is the canonical source of "what happened." Everything else is derived.

Properties:
- Append-only (no updates, no deletes)
- Immutable entries (a block, once appended, never changes)
- Ordered by arrival time
- Grouped into turns (open vs. sealed)

### 2. View Store — User Interaction State

Small, flat, fast to diff:

```
categoryLevels:     Record<Category, Level>   # visibility toggles
expansionOverrides: Map<BlockId, bool>         # per-block expand/collapse
followMode:         bool
activePanel:        PanelId
scrollPosition:     int
```

Key principle: **view state never lives on domain objects.** Today `expanded` and `_expandable` sit directly on FormattedBlock — that's view state contaminating the domain model. In the target architecture, expansion state lives in the View Store keyed by block ID, and expandability is a derived property (does the block exceed its truncation limit at the current level?).

### 3. Derived/Computed Layer — Not a Store, a Computation

Pure functions that combine the two stores:

```
visibleBlocks(domain, view) -> ResolvedBlock[]
renderedOutput(resolvedBlocks) -> RenderableStrips[]
```

Memoized so they only recompute when inputs change. This is where all the "intelligence" lives — visibility resolution, tool collapse, truncation decisions — but it owns no state.

## Data Flow

```
+---------------+     +---------------+
| WebSocket/    |     | User Input    |
| SSE from      |     | (keys,        |
| proxy         |     |  clicks)      |
+-------+-------+     +-------+-------+
        |                      |
        v                      v
+---------------+     +---------------+
| Domain Store  |     | View Store    |
| (append-only  |     | (levels,      |
|  block log)   |     |  overrides,   |
|               |     |  scroll)      |
+-------+-------+     +-------+-------+
        |                      |
        +----------+-----------+
                   |
                   v
          +----------------+
          | Derived Layer  |
          | (memoized)     |
          |                |
          | resolve(domain,|
          |   view) ->     |
          |   renderable   |
          +--------+-------+
                   |
                   v
          +----------------+
          | Render Layer   |
          | (viewport only)|
          +----------------+
```

## What This Buys Us

### Predictable Invalidation

When the user presses `3` to cycle tools visibility:

```
viewStore.categoryLevels.tools = nextLevel(current)
  -> derived layer recomputes visibleBlocks (memoized, only tools blocks re-resolve)
    -> render layer produces new output for affected blocks only
```

No imperative "clear overrides, re-render all turns, update scroll" chain. The derivation handles it.

### Trivial Streaming

New event arrives:

```
domainStore.append(newBlock)
  -> derived layer appends one resolved block (previous blocks unchanged, memo cache hit)
    -> render layer produces strips for the new block only
```

Append-only domain data means previous derivations are always valid.

### Undo/Debug for Free

View state is a plain object — snapshot it, restore it, time-travel through it. Domain data is an immutable log — replay from any point.

## Design Challenges

### Streaming Turns

A turn is either in-progress (blocks still arriving) or completed/sealed. The domain store needs this concept so the derived layer knows whether to re-derive on every append or wait for the turn to seal.

### Tool Collapse as Derivation

`collapse_tool_runs()` creates summary blocks from consecutive tool use/result pairs. This is a domain-level transformation — it creates new blocks from existing ones. It should live as a derived computation between the raw domain store and the visibility resolver, not as a mutation of the domain store. One place decides whether to collapse (single enforcer).

### Virtualized Rendering

With thousands of turns, only the viewport is rendered. The derived layer produces a virtual list — total height plus a function `renderRange(startLine, endLine)`. Scroll position (view state) determines which range to materialize.

### Settings Persistence

Settings are the persisted subset of view state. Load on startup to seed the view store. Save on change with debounced write. Settings are not a separate state system — they're serialization of a view state subset.

## Migration Path

This is not a rewrite. The existing two-stage pipeline (formatting -> rendering) and the FormattedBlock IR are the right shape. The change is making state ownership explicit:

1. **Extract view state off domain objects** — `expanded`, `_expandable` move out of FormattedBlock into a separate view state structure keyed by block ID.

2. **Formalize the domain store** — the append-only block log becomes an explicit, owned data structure rather than TurnData lists scattered across ConversationView.

3. **Make derivations pure** — visibility resolution and tool collapse become pure functions of (domain, view) rather than methods that read and mutate scattered state.

4. **Single render invalidation path** — any state change (new event OR view toggle) flows through the same derive-then-render pipeline. No separate code paths for "new data arrived" vs "user toggled visibility."
