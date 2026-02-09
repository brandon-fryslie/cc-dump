# cc-dump

Transparent HTTP proxy for monitoring Claude Code API traffic. Intercepts requests to the Anthropic API, tracks system prompt changes with diffs, and provides a real-time Textual TUI.

## Install

```bash
uv tool install -e .
```

Requires Python 3.10+. Single production dependency: [Textual](https://github.com/Textualize/textual).

## Usage

### Reverse Proxy Mode (default)

Point Claude Code at cc-dump, which forwards to the real API:

```bash
cc-dump [--port PORT] [--target URL]
ANTHROPIC_BASE_URL=http://127.0.0.1:3344 claude
```

### Forward Proxy Mode

For dynamic targets (e.g., non-Anthropic APIs):

```bash
cc-dump --port 3344 --target ""
HTTP_PROXY=http://127.0.0.1:3344 ANTHROPIC_BASE_URL=http://api.minimax.com claude
```

In forward proxy mode, requests are sent as plain HTTP to cc-dump, inspected, then upgraded to HTTPS for the upstream API. Set `ANTHROPIC_BASE_URL` to an HTTP URL (not HTTPS) to avoid TLS tunneling.

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--port PORT` | 3344 | Listen port |
| `--target URL` | `https://api.anthropic.com` | Upstream API URL (empty string for forward proxy mode) |
| `--seed-hue HUE` | 190.0 | Base hue for the color palette |
| `--db PATH` | auto | SQLite database path |

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
