# Errors

## Overview

A transparent proxy sits in a fragile position: upstream APIs return HTTP errors, network connections fail, and the TUI itself can encounter rendering exceptions during hot-reload cycles. If cc-dump swallowed these failures or crashed, users would lose visibility into exactly the moments that matter most -- when something goes wrong in the Claude Code session they're monitoring.

The error system has two distinct concerns:

1. **API/proxy errors in the conversation stream** -- HTTP errors and connection failures that are part of the monitored traffic. These appear inline as conversation blocks because they are data the user is observing.
2. **Application-level errors** -- unhandled exceptions and stale module state from hot-reload. These appear as an overlay indicator because they are about the tool itself, not the traffic it monitors.

## API and Proxy Errors (Conversation Blocks)

### Error Sources

Errors originate in the proxy layer and flow through the standard event pipeline:

| Source | Event Type | When |
|---|---|---|
| Upstream HTTP error (e.g., 429 rate limit, 500 server error) | `ErrorEvent(code, reason)` | `urllib.error.HTTPError` caught during request forwarding |
| Upstream target configuration error | `ErrorEvent(code, reason)` | Target has `error_reason` set (code defaults to `error_status` or 500) |
| Proxy-level failure (connection timeout, DNS failure, etc.) | `ProxyErrorEvent(error)` | Any non-HTTP `Exception` caught during request forwarding |

Both event types are only emitted if a request event was already emitted for the same request (i.e., the proxy had begun processing the request before the failure occurred).

### Block Types

Events are converted to `FormattedBlock` instances by the event handlers:

- **`ErrorBlock`** -- fields: `code` (int), `reason` (str). Represents an HTTP-level error from the Anthropic API.
- **`ProxyErrorBlock`** -- fields: `error` (str). Represents a transport-level failure in the proxy itself.

Both are added as single-block turns via `domain_store.add_turn([block])`.

### Visibility

Error blocks have **no category assignment** (`BLOCK_CATEGORY` maps them to `None`). The rendering pipeline treats `None`-category blocks as `ALWAYS_VISIBLE` -- they are always visible regardless of visibility level settings and cannot be hidden by toggling category visibility. They render at whatever the current level and expansion state dictates.

### Rendering

Error blocks participate in the standard 3-level visibility system with state-specific renderers:

**ErrorBlock:**

| Level | Collapsed | Expanded |
|---|---|---|
| Default (no category) | `[HTTP <code> <reason>]` in bold error color | Same as default |
| SUMMARY collapsed | `[HTTP <code>]` in bold error color | -- |
| SUMMARY expanded | `[HTTP <code> <reason>]` in bold error color | -- |
| FULL collapsed | `[HTTP <code> <reason>]` in bold error color | -- |

**ProxyErrorBlock:**

| Level | Collapsed | Expanded |
|---|---|---|
| Default (no category) | `[PROXY ERROR: <error>]` in bold error color, with leading newline | Same as default |
| SUMMARY collapsed | `[PROXY ERROR]` in bold error color | -- |
| SUMMARY expanded | `[PROXY ERROR: <error>]` in bold error color | -- |
| FULL collapsed | `[PROXY ERROR: <error>]` in bold error color | -- |

All error rendering uses the theme's `error` color (from `get_theme_colors()`).

### Logging

Both error types are logged at ERROR level to the Logs panel:
- HTTP errors: `"HTTP Error <code>: <reason>"`
- Proxy errors: `"Proxy error: <error>"`

### Export

Error blocks are included in text exports:
- `ErrorBlock`: `"Error: <code>"` with optional `"Reason: <reason>"`
- `ProxyErrorBlock`: `"Error: <error>"`

### Search

Error blocks are searchable:
- `ErrorBlock` text extraction: `"HTTP <code> <reason>"`
- `ProxyErrorBlock` text extraction: `"<error>"`

## Application Error Indicator (Overlay)

### Purpose

The error indicator is a small overlay that appears in the upper-right corner of the conversation viewport when the application itself has problems -- primarily unhandled exceptions and stale modules that need a restart. It exists because cc-dump is designed to keep running through errors (especially during hot-reload development), and users need to know when the tool is in a degraded state.

### Data Model

**`ErrorItem`** (frozen dataclass in `app/error_models.py`):
- `id` (str) -- unique identifier for deduplication
- `icon` (str) -- emoji displayed in the indicator
- `summary` (str) -- short description of the error

**`IndicatorState`** (mutable object in `tui/error_indicator.py`):
- `items: list[ErrorItem]` -- current error items to display
- `expanded: bool` -- whether the indicator is showing detail lines

### Error Item Sources

| Source | ID Pattern | Icon | Summary |
|---|---|---|---|
| Stale modules (stable boundary file changed on disk but cannot be hot-reloaded) | `"stale"` | cross mark (U+274C) | Module relative path (e.g., `pipeline/proxy.py`) |
| Unhandled exceptions (caught by `App._handle_exception`) | `"exc-<object_id>"` where object_id is `id(error)` | collision (U+1F4A5) | `"<ExceptionType>: <message>"` |
| Render-line exceptions (caught in `ConversationView.render_line`) | `"render:<ExceptionType>"` | warning (U+26A0 U+FE0F) | `"<ExceptionType>: <message>"` |

### State Management

Error items flow through two paths depending on their source:

**Path 1: Stale files and unhandled exceptions (via view store)**

1. **Stale files** are tracked in `view_store.stale_files` (an `ObservableList`), updated by `_update_staleness()` in `hot_reload_controller.py`. On every file change event, it calls `get_stale_excluded()` which compares current file hashes against startup hashes.
2. **Unhandled exception items** are tracked in `view_store.exception_items` (an `ObservableList`), appended by `App._handle_exception()`.
3. A **computed** (`view_store.error_items`) combines both: stale filenames are converted to `ErrorItem` instances (all sharing ID `"stale"`), then exception items are appended.
4. A **reaction** on `error_items` calls `App._sync_error_items()`, which projects the items to the active `ConversationView` via `conv.update_error_items()`.

**Path 2: Render-line exceptions (direct to widget)**

Render-line exceptions add items directly to the `ConversationView`'s local `_indicator_state` Observable (bypassing the view store), since they originate within the widget's `render_line()` method. The `_report_render_line_exception` method checks for duplicate IDs before appending.

**Reactive projection within ConversationView:**

The widget holds an `Observable[tuple[list, bool]]` called `_indicator_state` (items list + expanded flag). A `reaction` on this observable calls `_apply_indicator_state`, which copies the items and expanded flag to the `IndicatorState` rendering object, clears the line cache, and triggers a `refresh()`.

### Visual Behavior

**Collapsed state** (default): A 4-cell strip showing a cross mark emoji (" \u274c ") on a white background, positioned at the upper-right corner of the viewport. Width: 4 cells (`_COLLAPSED_WIDTH`) plus 1 cell padding (`_PADDING`), totaling 5 cells.

**Expanded state**: A header line plus one detail line per error item, all right-aligned in the viewport.
- Header: `" <icon> restart needed "` in bold black-on-white
- Detail lines: `"    <summary> "` in normal black-on-white
- Width: max of header width and all detail line widths, plus 1 cell padding

**Expansion trigger**: Mouse hover. When `on_mouse_move` detects the cursor is within the indicator's hit region (via `hit_test_event`), the indicator expands. When the cursor leaves, it collapses. There is no keyboard shortcut to expand the indicator. The mouse handling for error indicator expansion lives in `ConversationView.on_mouse_move` (`widget_factory.py`), not in `error_indicator.py` itself.

### Compositing

The indicator is composited onto the conversation viewport during `render_line()` via `_overlay_line()`, which delegates to `error_indicator.composite_overlay()`. For each viewport line within the indicator's height:
1. The conversation content strip is cropped to `viewport_width - indicator_width` using `strip.crop_extend()`
2. The indicator strip segments for that line are appended to the cropped content segments
3. A combined `Strip` of the full viewport width is returned

Lines below the indicator's height pass through unmodified. When no error items exist, `indicator.height()` returns 0 and compositing is a no-op.

### Hit Testing

`hit_test_event()` determines whether a mouse coordinate falls within the indicator region:
- Returns `False` immediately if height is 0 (no items)
- Vertically: within `[0, indicator_height)`
- Horizontally: within `[viewport_width - indicator_width, viewport_width)`

The caller (`ConversationView.on_mouse_move`) translates the mouse event to content-relative coordinates via `event.get_content_offset(self)` before calling the hit test.

### Clearing Errors

- **Stale file errors** clear when the file content reverts to match its startup hash. `get_stale_excluded()` compares current hashes against `_excluded_hashes` captured at startup. If a file is edited back to its original content, it drops out of the stale list on the next file-change event. A successful hot-reload of reloadable modules does NOT clear staleness for stable boundary files, since those files are never reloaded.
- **Exception errors** are never cleared during a session. The `exception_items` ObservableList is only ever appended to (in `App._handle_exception`). There is no code path that removes items from it or calls `clear()` on it. They persist until the process exits.
- **Render-line errors** are deduplicated by exception type name (`"render:<TypeName>"`). `_report_render_line_exception` checks `if not any(item.id == err_key for item in items)` before appending. Once an error of a given type is added, subsequent errors of the same type are silently dropped. Like exception errors, render-line errors are never cleared during a session.

### Resilience Design

The app overrides `_handle_exception` (Textual's `App._handle_exception`) to catch unhandled exceptions without crashing. The comment in the code states: "DON'T call super() - keep running, hot reload will fix it." This reflects cc-dump's development model where hot-reload is the primary recovery mechanism -- the error indicator tells the user something broke, and a code fix + automatic reload is the expected resolution path.

Exception details are also logged: the full Python traceback is written to the Logs panel line by line, and buffered in `_error_log` for post-exit dump.

## Relationship Between the Two Error Systems

The two error systems are intentionally separate:

- **Conversation error blocks** are data being observed. They represent failures in the Claude Code session the user is monitoring. They flow through the standard pipeline (event -> formatting -> rendering) and are persisted in HAR recordings.
- **Application error items** are about the tool itself. They represent failures in cc-dump's own operation. They are transient UI state that does not persist.

A proxy error that prevents forwarding a request will produce both: an `ErrorEvent`/`ProxyErrorEvent` in the conversation stream (visible as a block), and if that error somehow causes an unhandled exception in event processing, an `ErrorItem` in the overlay. But these are independent paths serving different user needs.
