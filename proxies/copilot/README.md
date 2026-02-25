# Copilot Proxy Work Area

This directory holds Copilot-provider notes and assets for `cc-dump`.

- Runtime implementation lives in `/Users/bmf/code/cc-dump/src/cc_dump/proxies/copilot/`.
- This root-level folder is reserved for provider-specific docs/templates as we iterate.

Current supported routes in `provider=copilot` mode:
- `POST /v1/messages` (Anthropic-compatible; translated to Copilot chat-completions)
- `POST /v1/messages/count_tokens` (heuristic count endpoint)
- `GET /v1/models` (translated to Anthropic model-list shape)
- `GET /models` (OpenAI-style model list passthrough)
- `POST /v1/chat/completions` (OpenAI-compatible passthrough to Copilot)
- `POST /chat/completions` (OpenAI-compatible passthrough alias)
- `POST /v1/embeddings` (OpenAI-compatible passthrough to Copilot embeddings)
- `POST /embeddings` (OpenAI-compatible passthrough alias)
- `GET /usage` (GitHub Copilot usage endpoint passthrough)
- `GET /v1/usage` (compatibility alias)
- `GET /token` (resolved Copilot token visibility for debugging)
- `GET /v1/token` (compatibility alias)

Auth modes:
- `proxy_copilot_token`: direct Copilot bearer token
- `proxy_copilot_github_token`: GitHub token used to fetch/refresh Copilot token
- `proxy_copilot_rate_limit_seconds`: minimum interval between Copilot upstream calls
- `proxy_copilot_rate_limit_wait`: wait instead of returning 429 when rate limit is hit
- CLI helper: `cc-dump --proxy-auth copilot` runs GitHub device auth and saves provider settings
