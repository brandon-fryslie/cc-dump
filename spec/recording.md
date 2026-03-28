# Recording and Replay

**Status:** draft

## Why This Exists

Claude Code conversations are ephemeral. Once a session ends, the system prompts, tool invocations, token usage, and caching behavior that shaped the conversation are gone. Recording solves this: every API exchange is captured in a standard format so it can be replayed, analyzed, and compared later.

Recording also enables offline analysis. A user can capture a session during real work, then replay it later to study prompt changes, tool patterns, or token economics without running Claude Code.

The choice of HAR (HTTP Archive 1.2) as the recording format is deliberate: HAR is a widely-supported standard that can be opened in browser dev tools, Charles Proxy, and other HTTP analysis tools. cc-dump recordings are not locked into a proprietary format.

## What Gets Recorded

Every complete API request/response exchange is recorded as a HAR entry. Specifically:

- **Request headers** (as sent by Claude Code through the proxy, converted from dict to HAR's `[{name, value}]` format)
- **Request body** (the full JSON payload with `stream` rewritten to `false`)
- **Response status code** (from `ResponseHeadersEvent`)
- **Response headers** (synthetic `application/json` + `content-length`, plus original headers excluding `content-type`, `content-length`, and `transfer-encoding`)
- **Response body** (the complete API response message, reconstructed from SSE stream by `ResponseAssembler`)
- **Timing** (wall-clock duration from `RequestHeadersEvent` to `_commit_entry`, in milliseconds)
- **Provider identity** (stored in a `_cc_dump` custom field)

Incomplete exchanges (where the response never completes) are not recorded. The recorder accumulates state per-request and only commits a HAR entry on `RESPONSE_COMPLETE`.

## HAR Format

### Structure

Files conform to HAR 1.2. The top-level structure:

```json
{
  "log": {
    "version": "1.2",
    "creator": { "name": "cc-dump", "version": "0.2.0" },
    "entries": [ ... ]
  }
}
```

### Entry Structure

Each entry represents one complete API exchange:

```json
{
  "startedDateTime": "2026-03-28T14:30:00.000000+00:00",
  "time": 1234.5,
  "request": {
    "method": "POST",
    "url": "<canonical provider API endpoint>",
    "httpVersion": "HTTP/1.1",
    "headers": [ {"name": "...", "value": "..."}, ... ],
    "queryString": [],
    "postData": {
      "mimeType": "application/json",
      "text": "<JSON request body with stream=false>"
    },
    "headersSize": -1,
    "bodySize": <byte length of postData.text, UTF-8 encoded>
  },
  "response": {
    "status": 200,
    "statusText": "OK",
    "httpVersion": "HTTP/1.1",
    "headers": [
      {"name": "content-type", "value": "application/json"},
      {"name": "content-length", "value": "<byte length>"},
      ...
    ],
    "content": {
      "size": <byte length of text, UTF-8 encoded>,
      "mimeType": "application/json",
      "text": "<JSON complete message>"
    },
    "redirectURL": "",
    "headersSize": -1,
    "bodySize": <byte length of content.text, UTF-8 encoded>
  },
  "cache": {},
  "timings": {
    "send": 0,
    "wait": <total time in ms>,
    "receive": 0
  },
  "_cc_dump": {
    "provider": "anthropic"
  }
}
```

### Format Decisions and Trade-offs

The HAR file stores **synthetic non-streaming representations**, not raw wire traffic:

1. **Request body `stream` field is set to `false`.** The actual request has `stream: true` because cc-dump intercepts SSE streams. `build_har_request` copies the body and overwrites `stream` to `false` for clarity when viewing in standard HAR tools.

2. **Response is the complete reconstructed message**, not the sequence of SSE `content_block_delta` events. The `ResponseAssembler` (upstream in the proxy pipeline) reconstructs the full message from the SSE stream; the recorder captures that final form via `ResponseCompleteEvent.body`.

3. **Response headers are synthetic.** `build_har_response` always emits `content-type: application/json` and a computed `content-length` as the first two headers. Additional response headers from the actual response are appended, but `content-type`, `content-length`, and `transfer-encoding` are excluded (they would be inconsistent with the synthetic body).

4. **Timing is coarse.** All time is attributed to `timings.wait`; `send` and `receive` are zero. The `time` field and `timings.wait` both reflect total wall-clock milliseconds. Timing is measured from `RequestHeadersEvent` receipt to `_commit_entry` execution (not from the original request start to response end).

5. **Request URL comes from the provider registry**, not from the actual proxy request. Each `ProviderSpec` has a `har_request_url` field that provides the canonical upstream API endpoint URL. Current values: `https://api.anthropic.com/v1/messages` (anthropic), `https://api.openai.com/v1/chat/completions` (openai), `https://api.githubcopilot.com/chat/completions` (copilot).

6. **`statusText` is `"OK"` for status 200 and empty string for all other status codes.** This is a simplification; the recorder does not attempt to map other status codes to their standard reason phrases.

**Trade-off accepted:** HAR files are not wire-faithful. They show complete messages, not SSE chunks. This loses SSE-level timing granularity but gains standard format compatibility, simpler replay logic, and smaller files.

### Custom Fields

The `_cc_dump` object on each entry uses HAR's underscore-prefix convention for custom fields. Currently contains:

| Field | Type | Description |
|-------|------|-------------|
| `provider` | string | Provider key (e.g., `"anthropic"`, `"openai"`, `"copilot"`) |

## Recording Behavior

### Accumulation State Machine

The recorder (`HARRecordingSubscriber`) tracks per-request state in `_PendingExchange` dataclasses, keyed by `request_id` in an `OrderedDict`. The state machine processes four event kinds:

| Event Kind | Effect |
|---|---|
| `REQUEST_HEADERS` | Store request headers; record `request_start_time` (UTC now) |
| `REQUEST` | Store request body |
| `RESPONSE_HEADERS` | Store response status code and headers |
| `RESPONSE_COMPLETE` | Store complete message body, then call `_commit_entry` |

Provider identity is stamped on every event (resolved through the provider registry). The pending exchange is committed only when all required data is present: `request_body` and `complete_message` must both be non-None for `_commit_entry` to write.

### File Creation

Recording files are created **lazily**: the file is not written to disk until the first complete API exchange is committed. Sessions with no API traffic produce no file. This avoids cluttering the recordings directory with empty files from sessions that were started and immediately closed.

### Incremental Writing

Each HAR entry is written to disk immediately upon completion. The recorder maintains a valid HAR JSON structure at all times by:

1. Writing the HAR preamble (everything up to the `entries` array opening bracket) on first entry
2. Tracking `_entries_end_pos` (the file position after the last entry)
3. After each entry: seeking to `_entries_end_pos`, writing the entry (with comma separator if not the first), updating `_entries_end_pos`, then re-writing the closing `\n]}}` footer
4. Flushing after every entry

This means the file is always valid JSON, even if the process crashes mid-session.

### Per-Provider Separation

Each active provider gets its own `HARRecordingSubscriber` instance with a `provider_filter`. Events not matching the filter are silently ignored. The filter value is lowercased and trimmed (`str(provider_filter or "").strip().lower()`), but the event's provider field is compared as-is — this is only effectively case-insensitive because provider keys are lowercase by convention. This produces one HAR file per provider per session.

The subscribers are registered as `DirectSubscriber` instances on the `EventRouter`, meaning they run inline in the router thread.

### Bounded Pending State

The recorder tracks in-flight exchanges in an `OrderedDict` keyed by request ID (or `"__legacy__"` if `request_id` is falsy). To prevent unbounded memory growth from orphaned requests, the pending map is capped at 256 entries (configurable via `CC_DUMP_HAR_MAX_PENDING` environment variable, minimum 1). When the cap is exceeded, the oldest pending exchange is evicted with a warning log. The cap is enforced on every new request insertion, not on a timer. Additionally, `_pending_by_request.move_to_end(request_key)` is called on every event for existing pending entries, keeping recently-active entries at the end of the `OrderedDict` to prevent eviction of active exchanges (LRU behavior).

### Diagnostic Counters

The recorder maintains `_events_received`, a dict counting events by kind name. This is used only for diagnostic logging on close if events were received but no entries were written.

### Close Behavior

On close:
- If no file was created (`_file is None`): nothing happens. If events were received (but no entries committed), a warning is logged with the event counts.
- If a file was created but has zero entries (should not happen due to lazy init): the file is deleted and an error is logged. This is a belt-and-suspenders check.
- Pending incomplete exchanges are silently dropped (the `_pending_by_request` dict is abandoned).

### Error Isolation

All event handling is wrapped in a try/except in `on_event`. Errors are logged but never propagated to the router. Within `_commit_entry`, serialization errors are caught individually so a bad entry does not corrupt the file — the pending state for that request is still removed.

## Storage Layout

### Default Directory

Recordings are stored under:

```
~/.local/share/cc-dump/recordings/
```

This is a flat directory (no subdirectories per session or provider). All `.har` files live directly in this directory.

### Filename Convention

```
ccdump-<provider>-<timestamp>-<hash>.har
```

Where:
- `<provider>` is the provider key (e.g., `anthropic`, `openai`, `copilot`)
- `<timestamp>` is UTC formatted as `YYYYMMDD-HHMMSSZ` (e.g., `20260328-143000Z`)
- `<hash>` is the first 8 characters of a SHA-1 hash derived from `<provider>:<timestamp>:<pid>:<uuid4>`

Example: `ccdump-anthropic-20260328-143000Z-a1b2c3d4.har`

The hash component ensures uniqueness even if two sessions start in the same second.

### Custom Output Directory

The `--record <path>` flag overrides the output directory:
- If `<path>` is an existing directory, recordings are written there.
- If `<path>` has a `.har` extension, recordings are written to its parent directory.
- Otherwise, `<path>` is treated as a directory (will be created).

## Replay Behavior

### Loading

`load_har(path)` reads a HAR file and extracts valid request/response pairs. For each entry:

1. Request body is parsed from `request.postData.text` (must decode to a JSON object)
2. Response body is parsed from `response.content.text` (must decode to a JSON object)
3. Request headers are extracted from HAR's `[{name, value}]` format into a flat dict (later duplicate header names overwrite earlier ones)
4. Response status is extracted from `response.status` (defaults to 200 if missing)
5. Response headers are extracted the same way as request headers
6. Provider is inferred from the HAR entry using a precedence chain:
   - `_cc_dump.provider` custom field (normalized and validated against known providers)
   - URL-based detection from `request.url` (matched against `url_markers` in provider specs)
   - Response body shape detection (`type: "message"` = Anthropic, `object: "chat.completion"` = OpenAI)
   - Falls back to the default provider key (`"anthropic"`) if none of the above match
7. Response body is validated against the inferred provider's expected complete-response shape

Invalid entries are skipped with a warning log. If no valid entries remain after processing all entries, a `ValueError` is raised.

Exceptions raised: `ValueError` (invalid HAR structure or no valid entries), `FileNotFoundError` (file missing), `json.JSONDecodeError` (file is not valid JSON).

### Event Synthesis

Each valid HAR entry is converted to the same four pipeline events that live mode produces:

1. `RequestHeadersEvent` (seq=0) — carries request headers dict
2. `RequestBodyEvent` (seq=1) — carries request body dict
3. `ResponseHeadersEvent` (seq=2) — carries status code and response headers dict
4. `ResponseCompleteEvent` (seq=3) — carries complete message dict

Each entry gets a fresh `request_id` (UUID4 hex string via `new_request_id()`). All four events share the same `request_id` and `provider`. Events flow through the same `_handle_event` path that live events use, producing identical formatting and rendering.

### Timing

Replay is **instantaneous**: all entries are processed synchronously in sequence with no artificial delays. There is no attempt to reproduce original timing.

The replay flow:
1. `load_har()` returns a list of tuples (one per HAR entry)
2. This list is passed to `CcDumpApp` as `replay_data`
3. During app startup (via `lifecycle_controller._resume_or_replay`), `_process_replay_data()` iterates the list, calling `convert_to_events()` for each tuple and feeding the resulting events through `_handle_event()`
4. After all replay entries are processed, `_replay_complete` is set, unblocking the live event drain thread

This means replay must complete before any live events are consumed. The live event drain thread (`_drain_events`) calls `self._replay_complete.wait()` before entering its main loop.

### Replay + Live (Continue/Resume)

Replay can be combined with live proxy mode. The replay data is processed first (synchronously during app startup), then the live event queue starts draining. This means:

- `--continue` replays the latest recording, then continues capturing new live traffic.
- `--resume [path]` replays a specific recording (or latest if no path or `"latest"` given), then continues live.
- Both modes record new traffic to a fresh HAR file (unless `--no-record` is also passed).

Implementation: `--resume` and `--continue` both resolve to setting `args.replay` to the appropriate path. `--continue` is semantically equivalent to `--resume latest`.

## CLI Flags

### Recording Control

| Flag | Effect |
|------|--------|
| `--record <path>` | Set custom recording output directory |
| `--no-record` | Disable HAR recording entirely |

### Replay

| Flag | Effect |
|------|--------|
| `--replay <path>` | Replay a specific HAR file (live proxy is always started; new live traffic is also captured unless `--no-record`) |
| `--resume [path]` | Replay a recording then continue live. If no path or `"latest"`, replays latest recording. |
| `--continue` | Replay the latest recording then continue live. Equivalent to `--resume latest`. |

### Recording Administration

| Flag | Effect |
|------|--------|
| `--list-recordings` | List all recordings with metadata (provider, date, entry count, file size) and exit |
| `--cleanup-recordings [N]` | Delete older recordings, keeping newest N (default: 20), and exit |
| `--cleanup-dry-run` | When combined with `--cleanup-recordings`, preview what would be deleted without deleting |

### Environment Variables

| Variable | Default | Effect |
|----------|---------|--------|
| `CC_DUMP_HAR_MAX_PENDING` | `256` | Maximum number of in-flight request exchanges tracked by the recorder (minimum 1; non-integer values fall back to 256) |

### Restart Command

On shutdown, cc-dump logs a command to resume the session:

```
To resume: cc-dump --port <PORT> --resume <recording-path>
```

The recording path is resolved with a preference chain: the primary recording from this session (if the file exists on disk), otherwise the replay file that was loaded (if it exists). The `--port` uses the actual bound port from the current session.

## Known Divergences Between Live and Replay

These are documented and accepted consequences of the synthetic HAR format:

| Aspect | Live Mode | Replay Mode | Impact |
|--------|-----------|-------------|--------|
| `stream` in request body | `true` | `false` | `MetadataBlock` shows streaming status differently |
| Response content-type header | `text/event-stream` | `application/json` | Visible in header display if headers are shown |
| `TextDeltaEvent` / streaming events | Multiple (one per SSE chunk) | Zero (content arrives pre-assembled in `ResponseCompleteEvent`) | Semantic content is identical; streaming animation is absent in replay |
| Timing granularity | Real wall-clock per SSE event | Single total duration per exchange | No per-chunk timing in replay |
| Request URL | Local proxy address (e.g., `http://127.0.0.1:5000`) | Canonical provider API endpoint (e.g., `https://api.anthropic.com/v1/messages`) | Headers category shows different values |
| Response headers | Original from upstream API | Synthetic (`application/json` + `content-length` + preserved extras minus content-type/content-length/transfer-encoding) | Headers category shows different values |

## Cleanup and Retention

The `cleanup_recordings` function provides basic retention management:

- Recordings are sorted by creation timestamp (from the first HAR entry's `startedDateTime`, falling back to file modification time)
- The newest N recordings are kept; older ones are deleted
- Default retention is 20 recordings (set by CLI `--cleanup-recordings` default, not by `cleanup_recordings` function which also defaults to 20)
- Dry-run mode previews without deleting
- Cleanup is a one-shot CLI command, not an automatic background process
- The `keep` parameter is clamped to a minimum of 0 (negative values become 0)

## Recording Metadata Query

`list_recordings()` returns metadata for each `.har` file in the recordings directory:

| Field | Source |
|-------|--------|
| `path` | Absolute filesystem path (as string) |
| `filename` | Basename |
| `provider` | Inferred from filename pattern first (`ccdump-<provider>-...`, validated against canonical provider keys), falling back to first HAR entry inspection via `detect_provider_from_har_entry` |
| `created` | From first entry's `startedDateTime`, falling back to file mtime (UTC ISO format) |
| `entry_count` | Number of entries in the HAR log |
| `size_bytes` | File size on disk |

Results are sorted by filename (alphabetical, from `Path.glob` sorted output).

`get_latest_recording()` returns the path to the most recently created recording, sorted by `created` timestamp (not filename). This differs from `list_recordings()` ordering. Returns `None` if no recordings exist.

Provider inference from the filename uses the `ccdump-<provider>-...` prefix pattern: the filename is split on `-` with a max of 4 parts, and `parts[1]` is checked against the canonical provider registry. This avoids parsing the full HAR JSON for the common case. If the filename pattern does not match (e.g., a manually-named HAR file), the first entry is loaded and passed to `detect_provider_from_har_entry`.
