# Copilot Support: Slice-by-Slice Evaluation

## Scope
This evaluates the Copilot proxy work implemented so far in `cc-dump`, relative to the reference behavior in `/Users/bmf/code/ericc-ch_copilot-api` and current product goals (live configurability, route compatibility, and robust proxy behavior).

## Summary
- Overall status: **strong partial completion**.
- Core capabilities are implemented and tested.
- Remaining work is mostly around production-hardening and deeper integration tests (real upstream behavior under failure/latency/stream edge cases).

## Slice Status Matrix

| Slice | Status | Evidence | Notes |
|---|---|---|---|
| Runtime provider abstraction (`anthropic`/`copilot`) | Complete | `src/cc_dump/proxies/runtime.py`, `tests/test_proxy_runtime.py` | Provider switching and normalization are in place. |
| Settings schema + reactive runtime sync | Complete | `src/cc_dump/app/settings_store.py`, `src/cc_dump/tui/settings_panel.py` | Includes Copilot fields, secrets, and runtime update reaction. |
| CLI startup/env wiring for Copilot | Complete | `src/cc_dump/cli.py` | Supports env overrides including rate-limit settings. |
| Device auth flow (`--copilot-auth`) | Complete | `src/cc_dump/proxies/copilot/auth.py`, `tests/test_copilot_auth.py` | Persists GitHub token and performs preflight token resolution. |
| Token resolution and refresh via GitHub endpoint | Complete | `src/cc_dump/proxies/copilot/token_manager.py`, `tests/test_copilot_token_manager.py` | Explicit token preferred, GitHub fallback cached/refreshed. |
| Anthropic->OpenAI request translation | Complete | `src/cc_dump/proxies/copilot/translation.py`, `tests/test_copilot_translation.py` | Handles system, text, thinking, tool use/result, tool choices. |
| OpenAI->Anthropic response translation (non-stream) | Complete | `src/cc_dump/proxies/copilot/translation.py`, `tests/test_copilot_translation.py` | Maps usage and stop reasons. |
| Streaming translation to Anthropic SSE events | Complete | `src/cc_dump/proxies/copilot/translation.py`, `src/cc_dump/pipeline/proxy.py` | Includes tool call deltas, message lifecycle, error SSE fallback. |
| Copilot endpoint handling in proxy | Complete | `src/cc_dump/pipeline/proxy.py` | Routes implemented for messages/models/chat/embeddings/usage/token/count_tokens. |
| OpenAI compatibility alias routes | Complete | `src/cc_dump/pipeline/proxy.py`, `tests/test_copilot_proxy_routes.py` | Includes `/chat/completions`, `/embeddings`, `/models` and v1 forms. |
| Utility alias routes (`/v1/usage`, `/v1/token`) | Complete | `src/cc_dump/pipeline/proxy.py`, `tests/test_copilot_proxy_routes.py` | Added in latest slice for compatibility consistency. |
| Copilot request rate limiting | Complete | `src/cc_dump/proxies/copilot/rate_limit.py`, `tests/test_copilot_rate_limit.py` | Supports reject mode (429) and wait mode. |
| Count-tokens endpoint heuristic + fallback | Complete | `src/cc_dump/proxies/copilot/provider.py`, `tests/test_copilot_provider.py` | Uses heuristic and now returns safe fallback on translation/count failures. |
| Docs scaffolding for Copilot area | Partial | `proxies/copilot/README.md` | Functional but still minimal compared to implementation breadth. |

## Endpoint Parity Snapshot

| Endpoint | Status in `cc-dump` |
|---|---|
| `POST /v1/messages` | Implemented (translation + stream/non-stream) |
| `POST /v1/messages/count_tokens` | Implemented (heuristic + fallback) |
| `GET /v1/models` | Implemented (Anthropic-shaped translation) |
| `GET /models` | Implemented (OpenAI passthrough) |
| `POST /v1/chat/completions` | Implemented (OpenAI passthrough) |
| `POST /chat/completions` | Implemented (alias) |
| `POST /v1/embeddings` | Implemented (OpenAI passthrough) |
| `POST /embeddings` | Implemented (alias) |
| `GET /usage` | Implemented (GitHub endpoint passthrough) |
| `GET /v1/usage` | Implemented (alias) |
| `GET /token` | Implemented (resolved token endpoint) |
| `GET /v1/token` | Implemented (alias) |

## Quality/Verification Snapshot

- Copilot-focused tests currently pass:
  - `tests/test_copilot_auth.py`
  - `tests/test_copilot_token_manager.py`
  - `tests/test_copilot_provider.py`
  - `tests/test_copilot_translation.py`
  - `tests/test_copilot_proxy_routes.py`
  - `tests/test_copilot_rate_limit.py`
  - `tests/test_proxy_runtime.py`
- Regression subset also passes:
  - `tests/test_sentinel.py`
  - `tests/test_har_recorder.py`
  - `tests/test_event_types.py`

## Key Risks / Gaps Remaining

1. Integration realism gap:
   - Current tests are mostly unit-level/mocked.
   - Missing an end-to-end test harness against realistic upstream SSE edge patterns.

2. Error-shape consistency across non-Anthropic passthrough routes:
   - `/v1/messages` has explicit Anthropic-shaped error mapping.
   - Other passthrough routes mostly relay upstream payloads directly.
   - This is acceptable, but should be explicitly standardized by contract.

3. Docs gap:
   - Operator-facing guidance (auth precedence, route semantics, and troubleshooting) is still lightweight.

4. Proxy handler complexity:
   - Copilot handling inside `src/cc_dump/pipeline/proxy.py` is large.
   - Functional now, but should be decomposed into endpoint handlers for maintainability.

## Recommended Next Slices

1. Add integration tests for streaming edge cases:
   - partial JSON deltas
   - malformed SSE lines
   - mid-stream upstream disconnects

2. Extract Copilot route handlers from `pipeline/proxy.py` into dedicated module(s) to reduce complexity and improve testability.

3. Define and enforce explicit error-shape policy per endpoint family:
   - Anthropic-compatible endpoints
   - OpenAI-compatible endpoints
   - utility/debug endpoints

4. Expand Copilot operator docs:
   - auth/token precedence
   - rate-limit behavior matrix
   - provider-switching examples
