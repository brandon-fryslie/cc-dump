# cc-dump

Transparent HTTP proxy for monitoring Claude Code API traffic. Intercepts requests to the Anthropic API, tracks system prompt content across requests, and shows diffs when prompts change.

## Install

```
uv tool install -e .
```

## Usage

### Reverse Proxy Mode (fixed target)

```
cc-dump [--port PORT] [--target URL]
ANTHROPIC_BASE_URL=http://127.0.0.1:3344 claude
```

### Forward Proxy Mode (dynamic targets)

```
cc-dump --port 3344 --target ""
HTTP_PROXY=http://127.0.0.1:3344 ANTHROPIC_BASE_URL=http://api.minimax.com claude
```

In forward proxy mode, requests are sent as plain HTTP to cc-dump, inspected, then upgraded to HTTPS for the upstream API. Set `ANTHROPIC_BASE_URL` to an HTTP URL (not HTTPS) to avoid TLS tunneling.

### Options

- `--port PORT` - Listen port (default: 3344)
- `--target URL` - Upstream API URL for reverse proxy mode (default: https://api.anthropic.com, use empty string for forward proxy mode)

## What it shows

- Full request details (model, max_tokens, stream, tool count)
- System prompts with color-coded tracking tags (`[sp-1]`, `[sp-2]`, etc.)
- Unified diffs when a prompt changes between requests
- Message roles and content summaries
- Streaming response text in real time

## TUI Controls

The TUI provides keyboard shortcuts to toggle different views. Active filters are indicated by colored vertical bars (▌) at the start of filtered content:

- **h** - Toggle Headers (cyan **▌** indicator) - Show/hide request/response headers
- **t** - Toggle Tools (blue **▌** indicator) - Show/hide tool use and tool result blocks
- **s** - Toggle System (yellow **▌** indicator) - Show/hide system prompts and tracked content
- **e** - Toggle Context (green **▌** indicator) - Expand/collapse full content of system prompts and show detailed token breakdowns
- **m** - Toggle Metadata (magenta **▌** indicator) - Show/hide model info, stop reasons, and other metadata
- **a** - Toggle Stats - Show/hide token statistics panel
- **c** - Toggle Cost - Show/hide per-tool token usage and cost aggregates
- **l** - Toggle Timeline - Show/hide per-turn context growth timeline

Each type of filtered content has a colored vertical bar (**▌**) indicator at the start of the line, making it easy to see which filter controls that content at a glance.

Active filters are shown in the filter status bar above the footer with their corresponding colored indicators.

No external dependencies — stdlib only.
