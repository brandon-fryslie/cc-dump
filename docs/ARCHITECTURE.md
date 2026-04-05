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
 TUI path   Analytics path
    │         │
    ▼         ▼
┌────────┐ ┌──────────────────┐
│ event_ │ │ analytics_store.py│  In-memory analytics
│handlers│ └──────────────────┘
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
| `MessageBlock` | Message role label and content |
| `TextContentBlock` | Plain text content |
| `ConfigContentBlock` | Configuration/system prompt content section |
| `ToolUseBlock` | Tool invocation (name, input size, detail) |
| `ToolResultBlock` | Tool result (size, error flag, correlated name) |
| `TextDeltaBlock` | Streaming text fragment |
| `TurnBudgetBlock` | Per-category token breakdown |
| `StreamInfoBlock` | SSE event metadata |

Blocks carry data, not presentation. A `ToolUseBlock` has `name`, `input_size`, `detail`, `tool_use_id` — not colors or formatting.

## Event Flow

The proxy emits raw events into a queue. The `EventRouter` fans them out to three subscribers:

1. **QueueSubscriber** (TUI): Events are queued, drained by `app.py`'s worker thread, dispatched to `event_handlers.py` which calls formatting and updates widgets.

2. **DirectSubscriber** (Analytics): `analytics_store.py` receives events inline, accumulates request/response data, and stores completed turns in memory for analytics panels.

3. **DirectSubscriber** (HAR): `har_recorder.py` accumulates events inline, reconstructs complete messages, and writes HAR 1.2 entries.

Events in order per API call:
```
request_headers → request_body → response_headers → response_progress* → response_complete → response_done
```

## Recording and Replay

cc-dump records all API traffic to HAR (HTTP Archive) 1.2 format for replay and offline analysis.

**Architecture principles:**
- **HAR files are the source of truth** for raw event data (complete, ordered, replayable)
- **In-memory analytics store is derived** runtime data for analytics panels (tokens, tools)
- **Zero divergence:** Live and replay modes use identical code paths downstream of event emission

### Live Mode (Recording)

```
proxy.py (HTTP intercept)
    ↓ emits events
router.py
    ├→ TUI subscriber (display)
    ├→ Analytics subscriber (analytics)
    └→ HAR subscriber (recording)
        └→ har_recorder.py
            - Accumulates SSE events in memory
            - Reconstructs complete messages
            - Writes HAR on response_complete
```

### Replay Mode

```
har_replayer.py (load HAR file)
    ↓ synthesizes events
router.py (same as live)
    ├→ TUI subscriber (display)
    ├→ Analytics subscriber (analytics)
    └→ (no recording in replay mode)
```

**Key insight:** Replay feeds synthetic events to the SAME router that live mode uses. Everything downstream (formatting, rendering, analytics) is identical.

### HAR Format Decisions

HAR files store **synthetic non-streaming responses** (not raw SSE streams):
- Request body: `stream=false` (for clarity in HAR viewers)
- Response content: Complete message in non-streaming format
- **Trade-off accepted:** HAR is not wire-faithful (shows complete messages, not SSE chunks)
- **Benefit gained:** Standard format, tool compatibility, simpler replay

When replaying:
1. `har_replayer.load_har()` extracts complete request/response pairs
2. `convert_to_events()` synthesizes SSE event sequence from complete message
3. Events match exactly what `proxy.py` emits during live capture
4. Same formatting pipeline produces identical FormattedBlocks

### Semantic Divergences (Acceptable)

Between live and replay modes:
- **MetadataBlock.stream:** `true` in live, `false` in replay (cosmetic)
- **Response headers:** `text/event-stream` in live, `application/json` in replay (cosmetic)
- **TextDeltaBlock count:** Multiple chunks in live, consolidated in replay (semantic content identical)

These divergences are documented, tested, and accepted as part of the HAR format decision.

### Session Management

Recordings stored in `~/.local/share/cc-dump/recordings/<session>/<provider>/recording-<timestamp>.har`

CLI commands:
- `cc-dump --list` — List available recordings with metadata (date, size, entry count)
- `cc-dump --replay <path>` — Replay a specific HAR file
- `cc-dump --replay latest` — Replay most recent recording
- `cc-dump --no-record` — Disable recording (live mode only)

## Virtual Rendering

`ConversationView` uses Textual's Line API instead of appending child widgets. Each completed API exchange becomes a `TurnData`:

```python
TurnData:
    blocks: list[FormattedBlock]     # hierarchical source of truth
    strips: list[Strip]              # pre-rendered lines
    block_strip_map: dict            # block index → first strip line
    relevant_filter_keys: set        # categories relevant to this turn
    is_streaming: bool               # whether turn is still streaming
```

`render_line(y)` uses binary search over turn offsets to find the right turn, then indexes into its strips. Cost: O(log n) lookup, O(viewport) rendering.

When filters change, only affected turns re-render (tracked via `relevant_filter_keys` per turn).

### Why render_line, Not Widgets

ConversationView uses `render_line()` + `Style.from_meta()` for interactive elements (expand/collapse arrows). This is the same pattern Textual's own `Tree` widget uses internally — it is the endorsed approach for virtual-scrolling content.

Widget-based alternatives were evaluated and rejected:

- **Widget-per-block** (ScrollableContainer + Static/Collapsible): No virtual rendering. All children are fully rendered in the DOM. A conversation with 1000+ blocks degrades at ~500 widgets.
- **Turn-level widgets** (ListView): Non-virtual. 100+ turns in long sessions hits the widget limit. Replaces O(log n) binary search with O(n) layout.
- **Arrow overlay widgets**: Overlay positioning with virtual scroll is harder than the meta approach. Adds a second mechanism for the same outcome.

Click targets are isolated via segment metadata. Content clicks produce empty meta and are ignored. This provides precise hit-testing without DOM nodes.

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

## Analytics Store

`analytics_store.py` is an in-memory store that accumulates request/response pairs into completed turns with token counts and tool invocations. It supports state serialization for hot-reload preservation via `get_state()` / `restore_state()`.

**HAR files are the persistent source of truth.** The analytics store is runtime-only derived data for analytics panels. In principle, it could be rebuilt by replaying HAR files.

## Filter System

Six content categories, each with visibility state (`VisState`: visible, full, expanded):

- **Categories:** USER, ASSISTANT, TOOLS, SYSTEM, METADATA, THINKING

Visibility state lives in a SnarfX `HotReloadStore` (`app/view_store.py`), not as reactive attributes in `app.py`. The view store schema is built programmatically from `CATEGORY_CONFIG`. Each category has three boolean axes: `vis:<name>`, `full:<name>`, `exp:<name>`. Changes trigger re-rendering of affected turns via `relevant_filter_keys` per turn.

## Tool Correlation

Tool uses and results are correlated by `tool_use_id`:

- In `formatting.py`: As tool_use blocks are processed, their IDs are recorded in a per-request map. When a tool_result references an ID, it inherits the tool's name, color, and detail string.
- In `core/analysis.py`: `correlate_tools()` produces matched `ToolInvocation` pairs for analytics storage and aggregate analysis.
- In `rendering.py`: Correlated blocks share the same color index for visual grouping.

## Color System

`palette.py` generates perceptually distinct colors using golden-angle (137.508°) spacing in HSL. Two lightness levels per hue: bright for text on dark backgrounds, dark for background tints.

The palette is initialized once at startup (`cli.py` calls `init_palette()`). Semantic colors (error, warning, success, info) and role colors (user, assistant, system) are fixed positions. Filter colors use a separate warm→cool gradient.

## Hot-Reload System

See `HOT_RELOAD_ARCHITECTURE.md` for full details.

Modules are classified as **stable** (never reload) or **reloadable** (reload on file change):

Stable boundaries (from `_EXCLUDED_FILES` and `_EXCLUDED_MODULES` in `app/hot_reload.py`) include `pipeline/proxy.py`, `cli.py`, `pipeline/event_types.py`, `tui/app.py`, and others. Reloadable modules (from `_RELOAD_ORDER`) include 44 modules spanning `core/`, `tui/`, and `app/` packages.

**Critical rule:** Stable modules must use `import cc_dump.module`, never `from cc_dump.module import func`. Direct imports create stale references that survive reload.

Reloadable modules are reloaded in dependency order (leaves first). Widgets are hot-swapped using the `get_state()` / `restore_state()` protocol.

## Module Dependency Graph

The authoritative reload order and exclusion lists are in `app/hot_reload.py`. Consult `_RELOAD_ORDER`, `_EXCLUDED_FILES`, and `_EXCLUDED_MODULES` directly for the current state.

Dependencies are strictly one-way. No cycles.
