# ARCHITECTURE.md

## System Overview

cc-dump is a three-layer system: **proxy** (HTTP interception) → **IR** (structured formatting) → **TUI** (display). Data flows strictly downward through these layers.

```
Claude Code (HTTP client)
       │
       ▼
┌─────────────────┐
│    proxy.py     │  HTTP intercept, emits raw events
└────────┬────────┘
         ▼
┌─────────────────┐
│    router.py    │  Fan-out to subscribers
└───┬─────────┬───┘
    ▼         ▼
 TUI path   DB path
    │         │
    ▼         ▼
┌────────┐ ┌─────────┐
│ event_ │ │ store.py │  SQLite persistence
│handlers│ └─────────┘
└───┬────┘
    ▼
┌──────────────┐
│formatting.py │  API JSON → FormattedBlock IR
└───┬──────────┘
    ▼
┌──────────────┐
│ rendering.py │  FormattedBlock → Rich Text → Strips
└───┬──────────┘
    ▼
┌───────────────────┐
│ widget_factory.py │  TurnData storage, virtual rendering
└───────────────────┘
```

## The Two-Stage Pipeline

The central architectural idea: **formatting is separate from rendering.**

**Stage 1 — `formatting.py`:** Parses API JSON into `FormattedBlock` dataclasses. This is the intermediate representation (IR). It knows about API structure (messages, tool_use, tool_result, system prompts) but nothing about Rich, Textual, or how things look on screen.

**Stage 2 — `tui/rendering.py`:** Converts `FormattedBlock` objects into Rich `Text` objects, applying filter visibility, color schemes, and layout. The rendering layer knows about display but doesn't parse API JSON.

This separation means:
- Formatting logic can be tested without a TUI
- Rendering can change independently (colors, layout, indicators)
- Hot-reload works at either layer without affecting the other
- A non-TUI consumer could use the same IR

## FormattedBlock IR

The IR is a flat list of `FormattedBlock` subclasses. Key types:

| Block | Purpose |
|-------|---------|
| `HeaderBlock` | Request header (REQUEST #N) |
| `MetadataBlock` | Model, max_tokens, stop_reason |
| `RoleBlock` | Message role label (USER, ASSISTANT, SYSTEM) |
| `TextContentBlock` | Plain text content |
| `TrackedContentBlock` | Content-hashed system prompt section |
| `DiffBlock` | Unified diff when tracked content changes |
| `ToolUseBlock` | Tool invocation (name, input size, detail) |
| `ToolResultBlock` | Tool result (size, error flag, correlated name) |
| `TextDeltaBlock` | Streaming text fragment |
| `TurnBudgetBlock` | Per-category token breakdown |
| `StreamInfoBlock` | SSE event metadata |

Blocks carry data, not presentation. A `ToolUseBlock` has `name`, `input_size`, `detail`, `tool_use_id` — not colors or formatting.

## Event Flow

The proxy emits raw events into a queue. The `EventRouter` fans them out to two subscribers:

1. **QueueSubscriber** (TUI): Events are queued, drained by `app.py`'s worker thread, dispatched to `event_handlers.py` which calls formatting and updates widgets.

2. **DirectSubscriber** (SQLite): `store.py` receives events inline, accumulates request/response data, and commits completed turns to the database.

Events in order per API call:
```
request_headers → request → response_headers → response_event* → response_done
```

## Virtual Rendering

`ConversationView` uses Textual's Line API instead of appending child widgets. Each completed API exchange becomes a `TurnData`:

```python
TurnData:
    blocks: list[FormattedBlock]     # source of truth
    strips: list[Strip]              # pre-rendered lines
    block_strip_map: dict            # block index → first strip line
    line_offset: int                 # position in virtual space
```

`render_line(y)` uses binary search over turn offsets to find the right turn, then indexes into its strips. Cost: O(log n) lookup, O(viewport) rendering.

When filters change, only affected turns re-render (tracked via `relevant_filter_keys` per turn).

## Streaming

Streaming responses build incrementally:

1. `begin_streaming_turn()` — creates empty TurnData with `is_streaming=True`
2. `append_streaming_block()` — adds blocks; `TextDeltaBlock` objects accumulate in a buffer, rendered as a growing tail
3. `finalize_streaming_turn()` — consolidates all `TextDeltaBlock` fragments into a single `TextContentBlock`, full re-render

The stable/streaming strip boundary avoids re-rendering already-committed content on each delta.

## Content Tracking

System prompts are tracked across requests:

1. Each content section is hashed (SHA256)
2. First appearance: assigned a color-coded tag (`[sp-1]`, `[sp-2]`, etc.)
3. Repeated appearances: reference the existing tag
4. Changed content: show unified diff with old/new comparison

State is maintained in a dict passed through `format_request()`: positions, known hashes, ID counters.

## Database Layer

SQLite with WAL mode. Two key patterns:

**Content-addressed blob storage:** Strings ≥512 bytes are extracted to a `blobs` table keyed by SHA256, replaced with `{"__blob__": hash}` references in the turn JSON. This deduplicates repeated system prompts.

**Database as aggregate source of truth:** Token counts and tool statistics are queried from the database, not accumulated in memory. The stats panel, economics panel, and timeline panel all query `db_queries.py` which opens read-only connections.

Tables: `turns` (metadata + tokens), `blobs` (content-addressed), `turn_blobs` (links), `turns_fts` (full-text search), `tool_invocations` (per-tool stats).

## Filter System

Eight toggleable filters, each with a keybinding and colored indicator:

- **Content filters** (h, t, s, e, m): Control visibility of block types within turns. Managed by `render_blocks()` which checks `BLOCK_FILTER_KEY` mapping and returns `None` for hidden blocks.
- **Panel filters** (a, c, l): Show/hide aggregate panels (stats, economics, timeline).

Filter state lives as reactive attributes in `app.py`. Changes trigger `ConversationView.update_filters()` which re-renders only affected turns.

## Tool Correlation

Tool uses and results are correlated by `tool_use_id`:

- In `formatting.py`: As tool_use blocks are processed, their IDs are recorded in a per-request map. When a tool_result references an ID, it inherits the tool's name, color, and detail string.
- In `analysis.py`: `correlate_tools()` produces matched `ToolInvocation` pairs for database storage and aggregate analysis.
- In `rendering.py`: Correlated blocks share the same color index for visual grouping.

## Color System

`palette.py` generates perceptually distinct colors using golden-angle (137.508°) spacing in HSL. Two lightness levels per hue: bright for text on dark backgrounds, dark for background tints.

The palette is initialized once at startup (`cli.py` calls `init_palette()`). Semantic colors (error, warning, success, info) and role colors (user, assistant, system) are fixed positions. Filter colors use a separate warm→cool gradient.

## Hot-Reload System

See `HOT_RELOAD_ARCHITECTURE.md` for full details.

Modules are classified as **stable** (never reload) or **reloadable** (reload on file change):

| Stable boundaries | Reloadable modules |
|---|---|
| `proxy.py`, `cli.py`, `hot_reload.py` | `palette.py`, `colors.py`, `analysis.py` |
| `tui/app.py`, `tui/widgets.py` | `formatting.py`, `tui/rendering.py` |
| | `tui/event_handlers.py`, `tui/widget_factory.py` |
| | `tui/panel_renderers.py`, `tui/custom_footer.py` |

**Critical rule:** Stable modules must use `import cc_dump.module`, never `from cc_dump.module import func`. Direct imports create stale references that survive reload.

Reloadable modules are reloaded in dependency order (leaves first). If `widget_factory.py` is reloaded, widgets are hot-swapped using the `HotSwappableWidget` protocol (`get_state()` / `restore_state()`).

## Module Dependency Graph

```
Stable layer:
  cli.py → {router, store, app, palette}
  proxy.py → router
  app.py → {event_handlers, widget_factory, hot_reload, custom_footer}

Reloadable layer (reload order):
  1. palette.py
  2. colors.py → palette
  3. analysis.py (no deps)
  4. formatting.py → {colors, analysis}
  5. rendering.py → {formatting, palette}
  6. panel_renderers.py → analysis
  7. event_handlers.py → {formatting, analysis}
  8. widget_factory.py → {rendering, analysis, panel_renderers, db_queries}

Database layer:
  schema.py (no deps)
  store.py → {analysis, schema}
  db_queries.py → analysis
```

Dependencies are strictly one-way. No cycles.
