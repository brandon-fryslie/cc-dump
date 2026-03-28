# Errors

> Status: draft
> Last verified against: not yet

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

Error blocks have **no category assignment** (`BLOCK_CATEGORY` maps them to `None`). This means they are always visible regardless of visibility level settings -- they cannot be hidden by toggling category visibility. They render at whatever the current level and expansion state dictates.

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

### Error Item Sources

| Source | ID Pattern | Icon | Summary |
|---|---|---|---|
| Stale modules (hot-reload couldn't update a stable boundary module) | `"stale"` | cross mark | Module filename (last path component) |
| Unhandled exceptions (caught by `on_error` override) | `"exc-<object_id>"` | collision | `"<ExceptionType>: <message>"` |
| Render-line exceptions (caught in `render_line`) | `"render:<ExceptionType>"` | warning | `"<ExceptionType>: <message>"` |

### State Management

Error items flow through reactive state:

1. **Stale files** are tracked in `view_store.stale_files` (an `ObservableList`), updated by the hot-reload controller when it detects modules that couldn't be reloaded.
2. **Exception items** are tracked in `view_store.exception_items` (an `ObservableList`), appended by `App.on_error()`.
3. A **computed** (`view_store.error_items`) combines both lists: stale files are converted to `ErrorItem` instances, then exception items are appended.
4. A **reaction** on `error_items` calls `App._sync_error_items()`, which projects the canonical items to the active `ConversationView`'s indicator state.
5. Render-line exceptions add items directly to the `ConversationView`'s local indicator state (bypassing the view store) since they originate within the widget itself.

`IndicatorState` is a mutable object on each `ConversationView` with two fields:
- `items: list[ErrorItem]` -- current error items to display
- `expanded: bool` -- whether the indicator is showing detail lines

### Visual Behavior

**Collapsed state** (default): A single cell showing a cross mark emoji on a white background, positioned at the upper-right corner of the viewport. Width: 4 cells plus 1 cell padding.

**Expanded state**: A header line plus one detail line per error item, all right-aligned in the viewport.
- Header: `" <icon> restart needed "` in bold black-on-white
- Detail lines: `"    <summary> "` in normal black-on-white
- Width: max of header width and all detail line widths, plus 1 cell padding

**Expansion trigger**: Mouse hover. When `on_mouse_move` detects the cursor is within the indicator's hit region, the indicator expands. When the cursor leaves, it collapses. There is no keyboard shortcut to expand the indicator. Note: the mouse handling for error indicator expansion lives in `ConversationView` (`widget_factory.py`), not in `error_indicator.py` itself.

### Compositing

The indicator is composited onto the conversation viewport during `render_line()`. For each viewport line within the indicator's height:
1. The conversation content strip is cropped to `viewport_width - indicator_width`
2. The indicator strip for that line is appended
3. The combined strip is returned

Lines below the indicator's height pass through unmodified. When no error items exist, compositing is a no-op (height is 0).

### Hit Testing

`hit_test_event()` determines whether a mouse coordinate falls within the indicator region:
- Vertically: within `[0, indicator_height)`
- Horizontally: within `[viewport_width - indicator_width, viewport_width)`

This is used by `on_mouse_move` to toggle expansion.

### Clearing Errors

- **Stale file errors** can only clear if the file content is reverted to its startup content (matching the startup hash). A successful hot-reload of reloadable modules does NOT clear staleness for stable boundary files, since those files are never reloaded.
- **Exception errors** persist for the lifetime of the session. There is no manual dismiss mechanism. [UNVERIFIED: whether exception items are ever cleared, e.g., on successful hot-reload]
- **Render-line errors** are deduplicated by exception type name (`"render:<TypeName>"`). Once an error of a given type is added, subsequent errors of the same type are silently dropped.

### Resilience Design

The app overrides `on_error` to catch unhandled exceptions without crashing. The comment in the code states: "DON'T call super() - keep running, hot reload will fix it." This reflects cc-dump's development model where hot-reload is the primary recovery mechanism -- the error indicator tells the user something broke, and a code fix + automatic reload is the expected resolution path.

## Relationship Between the Two Error Systems

The two error systems are intentionally separate:

- **Conversation error blocks** are data being observed. They represent failures in the Claude Code session the user is monitoring. They flow through the standard pipeline (event -> formatting -> rendering) and are persisted in HAR recordings.
- **Application error items** are about the tool itself. They represent failures in cc-dump's own operation. They are transient UI state that does not persist.

A proxy error that prevents forwarding a request will produce both: an `ErrorEvent`/`ProxyErrorEvent` in the conversation stream (visible as a block), and if that error somehow causes an unhandled exception in event processing, an `ErrorItem` in the overlay. But these are independent paths serving different user needs.
