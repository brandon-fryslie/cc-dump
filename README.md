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

Filter toggles — each has a colored vertical bar indicator (`▌`) when active:

| Key | Filter | Indicator |
|-----|--------|-----------|
| `h` | Headers | cyan |
| `t` | Tools | blue |
| `s` | System prompts | yellow |
| `e` | Expand/context | green |
| `m` | Metadata | magenta |

Panel toggles:

| Key | Panel |
|-----|-------|
| `a` | Token statistics |
| `c` | Per-tool cost aggregates |
| `l` | Context growth timeline |

Navigation:

| Key | Action |
|-----|--------|
| `j` / `k` | Next / previous turn |
| `n` / `N` | Next / previous tool turn |
| `g` / `G` | Jump to first / last turn |

## Development

```bash
just run                          # Run the proxy
uv run pytest                     # All tests
uv run pytest -k "test_name"      # Single test
just lint                         # uvx ruff check src/
just fmt                          # uvx ruff format src/
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design and [PROJECT_SPEC.md](PROJECT_SPEC.md) for project goals.
