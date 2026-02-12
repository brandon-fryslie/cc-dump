# cc-dump

Transparent HTTP proxy for monitoring Claude Code API traffic. Intercepts requests to the Anthropic API, tracks system prompt changes with diffs, and provides a real-time Textual TUI.

## Install

```bash
uv tool install -e .
```

Requires Python 3.10+. Production dependencies: [Textual](https://github.com/Textualize/textual), [textual-serve](https://github.com/Textualize/textual-serve), tiktoken.

## Usage

### Browser Mode

Run cc-dump in your browser using textual-serve:

```bash
cc-dump-serve
# Visit http://localhost:8000
# Each browser tab runs an independent cc-dump instance
```

Or using the justfile:

```bash
just web
```

### Terminal Mode

#### Reverse Proxy Mode (default)

Point Claude Code at cc-dump, which forwards to the real API:

```bash
cc-dump [--port PORT] [--target URL]
# cc-dump will print the assigned port (OS-assigned by default)
# Example output: "Listening on: http://127.0.0.1:12345"
ANTHROPIC_BASE_URL=http://127.0.0.1:12345 claude  # use the port from cc-dump output
```

#### Forward Proxy Mode

For dynamic targets (e.g., non-Anthropic APIs):

```bash
cc-dump --target ""
# cc-dump will print the assigned port
# Example output: "Listening on: http://127.0.0.1:12345"
HTTP_PROXY=http://127.0.0.1:12345 ANTHROPIC_BASE_URL=http://api.minimax.com claude
```

In forward proxy mode, requests are sent as plain HTTP to cc-dump, inspected, then upgraded to HTTPS for the upstream API. Set `ANTHROPIC_BASE_URL` to an HTTP URL (not HTTPS) to avoid TLS tunneling.

#### Recording and Replay

cc-dump automatically records all API traffic to HAR files for later replay:

```bash
# Normal operation - records to ~/.local/share/cc-dump/recordings/
cc-dump

# Replay a previous session (proxy still runs for new traffic)
cc-dump --replay path/to/recording.har
cc-dump --replay latest  # replay most recent recording

# Continue from most recent recording (replay + capture new traffic)
cc-dump --continue

# List available recordings
cc-dump --list

# Disable recording
cc-dump --no-record

# Custom recording path
cc-dump --record /path/to/output.har
```

**Key features:**
- HAR files are the source of truth for events
- Replay mode loads previous data, then proxy accepts new traffic
- `--continue` combines replay with live capture for session continuity
- SQLite database provides analytics on recorded sessions

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--port PORT` | 0 (OS-assigned) | Listen port (0 = OS assigns an available port) |
| `--target URL` | `https://api.anthropic.com` | Upstream API URL (empty string for forward proxy mode) |
| `--replay PATH` | - | Replay a HAR file (`latest` for most recent) |
| `--continue` | - | Continue from most recent recording (replay + live) |
| `--record PATH` | auto | Custom HAR recording output path |
| `--no-record` | - | Disable HAR recording |
| `--list` | - | List available recordings and exit |
| `--db PATH` | auto | SQLite database path |
| `--no-db` | - | Disable database persistence |
| `--seed-hue HUE` | 190.0 | Base hue for the color palette |

## What It Shows

- Full request details (model, max_tokens, stream, tool count)
- System prompts with color-coded tracking tags (`[sp-1]`, `[sp-2]`, etc.)
- Unified diffs when a tracked prompt changes between requests
- Message roles and content summaries with tool correlation
- Streaming response text in real time
- Token statistics, per-tool cost breakdowns, and context growth timeline

## TUI Controls

### 3-Level Visibility System

Each content category has **3 visibility levels** (EXISTENCE · → SUMMARY ◐ → FULL ●). Press a key to cycle through levels:

| Key | Category | Default | What It Shows |
|-----|----------|---------|---------------|
| `h` | Headers | · | Separators, turn headers, HTTP headers |
| `u` | User | ● | User messages and inputs |
| `a` | Assistant | ● | Assistant responses |
| `t` | Tools | ◐ | Tool use/results (summarized or detailed) |
| `s` | System | ◐ | System prompts, tracked content with diffs |
| `m` | Metadata | · | Request/response metadata |
| `e` | Budget | · | Token accounting, cache stats |

**Level meanings:**
- `·` **EXISTENCE** — Minimal (1 line): content exists but details hidden
- `◐` **SUMMARY** — Compact (3-12 lines): meaningful preview without full details
- `●` **FULL** — Complete: all content visible

**Click to expand/collapse:** Click any block with `▶` to expand it or `▼` to collapse it within the current level.

**Example:** Press `t` to cycle tools: SUMMARY → FULL → EXISTENCE → SUMMARY. At FULL, individual tool blocks are shown. Click long results to collapse them.

See [docs/VISIBILITY_SYSTEM.md](docs/VISIBILITY_SYSTEM.md) for detailed documentation and examples.

### Panel Toggles

| Key | Panel |
|-----|-------|
| `c` | Per-tool cost aggregates |
| `l` | Context growth timeline |

### Search

| Key | Action |
|-----|--------|
| `/` | Start search (opens search bar at bottom) |
| `Enter` | Commit search and navigate to first match |
| `n` | Next match (in navigation mode) |
| `N` | Previous match (in navigation mode) |
| `Esc` | Cancel search and restore filters |

**Search modes** (toggle during editing with `Alt+key`):
- `Alt+c` — Case sensitivity toggle (default: insensitive)
- `Alt+w` — Word boundary matching
- `Alt+r` — Regex mode (default: on)
- `Alt+i` — Incremental search (default: on)

Search automatically raises category visibility to FULL and expands blocks containing matches.

### Other Controls

| Key | Action |
|-----|--------|
| `f` | Toggle follow mode (auto-scroll) |
| `q` | Quit |

## Development

```bash
just run                          # Run the proxy
uv run pytest                     # All tests
uv run pytest -k "test_name"      # Single test
just lint                         # uvx ruff check src/
just fmt                          # uvx ruff format src/
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design and [PROJECT_SPEC.md](PROJECT_SPEC.md) for project goals.
