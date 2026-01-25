# cc-dump

Transparent HTTP proxy for monitoring Claude Code API traffic. Intercepts requests to the Anthropic API, tracks system prompt content across requests, and shows diffs when prompts change.

## Install

```
uv tool install -e .
```

## Usage

```
cc-dump [--port PORT] [--target URL]
```

Then point Claude Code at the proxy:

```
ANTHROPIC_BASE_URL=http://127.0.0.1:3344 claude
```

### Options

- `--port PORT` - Listen port (default: 3344)
- `--target URL` - Upstream API URL (default: https://api.anthropic.com)

## What it shows

- Full request details (model, max_tokens, stream, tool count)
- System prompts with color-coded tracking tags (`[sp-1]`, `[sp-2]`, etc.)
- Unified diffs when a prompt changes between requests
- Message roles and content summaries
- Streaming response text in real time

No external dependencies — stdlib only.
