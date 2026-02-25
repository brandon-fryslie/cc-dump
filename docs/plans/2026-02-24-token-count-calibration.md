# Token Count Calibration Plan (fku.2)

Scope:
- compare provider usage totals vs local tiktoken estimate
- optionally compare provider totals vs Anthropic `count_tokens` captures
- derive deterministic fallback estimator bias per request-shape bucket

`// [LAW:one-source-of-truth] Provider usage totals are canonical when present in response.`
`// [LAW:verifiable-goals] Calibration output is machine-readable JSON with per-request rows + aggregate stats.`

## Script

Run:

```bash
uv run python -m cc_dump.experiments.token_count_calibration path/to/a.har path/to/b.har --json
```

Optional count map (captured from Anthropic `count_tokens` endpoint):

```bash
uv run python -m cc_dump.experiments.token_count_calibration path/to/a.har --count-map count_map.json --json
```

Count-map formats accepted:
- object map: `{ "request_key": 1234, "file.har:9": 567 }`
- list records: `[{"request_key":"...", "count_tokens_input_tokens":1234}]`

## Output contract

Report JSON includes:
- `rows`: per-request comparisons with `request_key`, deltas, and shape bucket
- `summary`: mean/median/p95/max deltas for `tiktoken_vs_provider` and `count_tokens_vs_provider`
- `summary.stratified_by_bucket`: same metrics per request-shape bucket
- `summary.known_mismatch_categories`: ranked mismatch buckets
- `proposed_algorithm`: explicit fallback estimator strategy

## Proposed algorithm for app implementation

1. Canonical input total for completed requests:
- `response.usage.input_tokens + response.usage.cache_read_input_tokens + response.usage.cache_creation_input_tokens`

2. Fallback only when canonical usage is unavailable (e.g. in-flight):
- `estimate = tiktoken(request_json) + bucket_bias_tokens.get(bucket, global_bias_tokens)`

3. Bucket derivation factors:
- prompt size (`short|medium|long`)
- tool density (`tool_light|tool_heavy`)
- cache mode (`cached|uncached`)
- content mix (`text_only|mixed|other`)

This keeps display correctness tied to provider truth while giving a deterministic temporary estimate path.
