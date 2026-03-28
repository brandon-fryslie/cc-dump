# Recording and Replay

**Status:** draft

## Why This Exists

Claude Code conversations are ephemeral. Once a session ends, the system prompts, tool invocations, token usage, and caching behavior that shaped the conversation are gone. Recording solves this: every API exchange is captured in a standard format so it can be replayed, analyzed, and compared later.

Recording also enables offline analysis. A user can capture a session during real work, then replay it later to study prompt changes, tool patterns, or token economics without running Claude Code.

The choice of HAR (HTTP Archive 1.2) as the recording format is deliberate: HAR is a widely-supported standard that can be opened in browser dev tools, Charles Proxy, and other HTTP analysis tools. cc-dump recordings are not locked into a proprietary format.

## What Gets Recorded

Every complete API request/response exchange is recorded as a HAR entry. Specifically:

- **Request headers** (as sent by Claude Code through the proxy)
- **Request body** (the full JSON payload, including messages, system prompts, tool definitions, model parameters)
- **Response status code**
- **Response headers** (synthetic, see format decisions below)
- **Response body** (the complete API response message, reconstructed from SSE stream)
- **Timing** (wall-clock duration from request start to response complete)
- **Provider identity** (which API provider the exchange targeted, stored in a `_cc_dump` custom field)

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
    "url": "<provider-specific URL>",
    "httpVersion": "HTTP/1.1",
    "headers": [ {"name": "...", "value": "..."}, ... ],
    "queryString": [],
    "postData": {
      "mimeType": "application/json",
      "text": "<JSON request body>"
    },
    "headersSize": -1,
    "bodySize": <byte length of postData.text>
  },
  "response": {
    "status": 200,
    "statusText": "OK",
    "httpVersion": "HTTP/1.1",
    "headers": [ {"name": "content-type", "value": "application/json"}, ... ],
    "content": {
      "size": <byte length>,
      "mimeType": "application/json",
      "text": "<JSON complete message>"
    },
    "redirectURL": "",
    "headersSize": -1,
    "bodySize": <byte length>
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

1. **Request body `stream` field is set to `false`.** The actual request has `stream: true` because cc-dump intercepts SSE streams. The HAR rewrites this for clarity when viewing in standard HAR tools.

2. **Response is the complete reconstructed message**, not the sequence of SSE `content_block_delta` events. The `ResponseAssembler` (upstream in the pipeline) reconstructs the full message from the SSE stream; the recorder captures that final form.

3. **Response headers are synthetic.** The live response uses `text/event-stream`; the HAR entry uses `application/json` with a computed `content-length`. Additional response headers from the actual response are preserved, excluding `content-type`, `content-length`, and `transfer-encoding` (which would be inconsistent with the synthetic body).

4. **Timing is coarse.** All time is attributed to `timings.wait`; `send` and `receive` are zero. The `time` field and `timings.wait` both reflect total wall-clock milliseconds.

5. **Request URL is derived from the provider registry** via the `har_request_url` field on `ProviderSpec`, not captured from the actual proxy request. This field provides the canonical URL written into HAR entries, reflecting the provider's API endpoint rather than the local proxy address.

**Trade-off accepted:** HAR files are not wire-faithful. They show complete messages, not SSE chunks. This loses SSE-level timing granularity but gains standard format compatibility, simpler replay logic, and smaller files.

### Custom Fields

The `_cc_dump` object on each entry uses HAR's underscore-prefix convention for custom fields. Currently contains:

| Field | Type | Description |
|-------|------|-------------|
| `provider` | string | Provider key (e.g., `"anthropic"`, `"openai"`) |

## Recording Behavior

### File Creation

Recording files are created **lazily**: the file is not written to disk until the first complete API exchange is committed. Sessions with no API traffic produce no file. This avoids cluttering the recordings directory with empty files from sessions that were started and immediately closed.

### Incremental Writing

Each HAR entry is written to disk immediately upon completion. The recorder maintains a valid HAR JSON structure at all times by:

1. Writing the HAR preamble (everything up to the `entries` array opening bracket)
2. After each entry: seeking to the end of the entries list, writing the entry (with comma separator if not the first), then re-writing the closing `]}}` footer

This means the file is always valid JSON, even if the process crashes mid-session. No explicit flush-on-close is needed.

### Per-Provider Separation

Each active provider gets its own `HARRecordingSubscriber` instance with a `provider_filter`. Events not matching the filter are silently ignored. This produces one HAR file per provider per session.

### Bounded Pending State

The recorder tracks in-flight exchanges in an `OrderedDict` keyed by request ID. To prevent unbounded memory growth from orphaned requests, the pending map is capped at 256 entries (configurable via `CC_DUMP_HAR_MAX_PENDING` environment variable). When the cap is exceeded, the oldest pending exchange is evicted with a warning log.

### Close Behavior

On close:
- If no file was created (no entries), nothing happens (no file to close).
- If a file was created but somehow has zero entries (should not happen due to lazy init), the file is deleted and an error is logged.
- Pending incomplete exchanges are silently dropped.

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
- `<provider>` is the provider key (e.g., `anthropic`, `openai`)
- `<timestamp>` is UTC formatted as `YYYYMMDD-HHMMSSZ` (e.g., `20260328-143000Z`)
- `<hash>` is the first 8 characters of a SHA-1 hash derived from `provider:timestamp:pid:uuid4`

Example: `ccdump-anthropic-20260328-143000Z-a1b2c3d4.har`

The hash component ensures uniqueness even if two sessions start in the same second.

### Custom Output Directory

The `--record <path>` flag overrides the output directory:
- If `<path>` is an existing directory, recordings are written there.
- If `<path>` ends in `.har`, recordings are written to its parent directory.
- Otherwise, `<path>` is treated as a directory to create.

## Replay Behavior

### Loading

`load_har(path)` reads a HAR file and extracts valid request/response pairs. For each entry:

1. Request body is parsed from `request.postData.text` (must be a JSON object)
2. Response body is parsed from `response.content.text` (must be a JSON object)
3. Request/response headers are extracted from HAR's `[{name, value}]` format
4. Provider is inferred from the HAR entry using a precedence chain:
   - `_cc_dump.provider` custom field (if present)
   - URL-based detection from `request.url`
   - Response body shape detection (Anthropic vs OpenAI format)
5. Response body is validated against the inferred provider's expected complete-response shape

Invalid entries are skipped with a warning. If no valid entries remain, a `ValueError` is raised.

### Event Synthesis

Each valid HAR entry is converted to the same four pipeline events that live mode produces:

1. `RequestHeadersEvent` (seq=0)
2. `RequestBodyEvent` (seq=1)
3. `ResponseHeadersEvent` (seq=2)
4. `ResponseCompleteEvent` (seq=3)

Each entry gets a fresh `request_id` (UUID4). Events flow through the same `_handle_event` path that live events use, producing identical formatting and rendering.

### Timing

Replay is **instantaneous**: all entries are processed synchronously in sequence with no artificial delays. There is no attempt to reproduce original timing. The replayer returns a list of synthesized events; blocking and completion coordination are handled by the caller, not by the replayer itself.

### Replay + Live (Continue/Resume)

Replay can be combined with live proxy mode. The replay data is processed first (synchronously), then the live event queue starts draining. This means:

- `--continue` replays the latest recording, then continues capturing new live traffic.
- `--resume [path]` replays a specific (or latest) recording, then continues live.
- Both modes record new traffic to a fresh HAR file (unless `--no-record` is also passed).

## CLI Flags

### Recording Control

| Flag | Effect |
|------|--------|
| `--record <path>` | Set custom recording output directory |
| `--no-record` | Disable HAR recording entirely |

### Replay

| Flag | Effect |
|------|--------|
| `--replay <path>` | Replay a specific HAR file (no live proxy unless proxy is also configured) |
| `--resume [path]` | Replay a recording then continue live. If no path given, replays latest recording. |
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
| `CC_DUMP_HAR_MAX_PENDING` | `256` | Maximum number of in-flight request exchanges tracked by the recorder |

### Restart Command

On shutdown, cc-dump prints a command to resume the session:

```
To resume: cc-dump --port <PORT> --resume <recording-path>
```

This uses whichever recording path is available: the primary recording from this session, or the replay file that was loaded.

## Known Divergences Between Live and Replay

These are documented and accepted consequences of the synthetic HAR format:

| Aspect | Live Mode | Replay Mode | Impact |
|--------|-----------|-------------|--------|
| `MetadataBlock.stream` | `true` | `false` | Cosmetic: metadata display shows streaming status |
| Response content-type header | `text/event-stream` | `application/json` | Cosmetic: visible in header display if headers are shown |
| `TextDeltaBlock` count | Multiple (one per SSE chunk) | Zero (content arrives pre-assembled in `ResponseCompleteEvent`) | Semantic content is identical; streaming animation is absent in replay |
| Timing granularity | Real wall-clock per SSE event | Single total duration per exchange | No per-chunk timing in replay |
| Request URL | Local proxy address | Canonical provider API endpoint | [UNVERIFIED] May affect header display |
| Response headers | Original from upstream API | Synthetic (`application/json` + `content-length` + preserved extras) | Headers category shows different values |

## Cleanup and Retention

The `cleanup_recordings` function provides basic retention management:

- Recordings are sorted by creation timestamp (from the first HAR entry's `startedDateTime`, falling back to file modification time)
- The newest N recordings are kept; older ones are deleted
- Default retention is 20 recordings
- Dry-run mode previews without deleting
- Cleanup is a one-shot CLI command, not an automatic background process

## Recording Metadata Query

`list_recordings()` returns metadata for each `.har` file in the recordings directory:

| Field | Source |
|-------|--------|
| `path` | Absolute filesystem path |
| `filename` | Basename |
| `provider` | Inferred from filename pattern, falling back to first HAR entry inspection |
| `created` | From first entry's `startedDateTime`, falling back to file mtime |
| `entry_count` | Number of entries in the HAR log |
| `size_bytes` | File size on disk |

Results are sorted by filename.

`get_latest_recording()` returns the path to the most recently created recording, sorted by created timestamp (not filename). This differs from `list_recordings()` ordering.

Provider inference from the filename uses the `ccdump-<provider>-...` prefix pattern, validated against the canonical provider registry. This avoids parsing the full HAR JSON for the common case.
