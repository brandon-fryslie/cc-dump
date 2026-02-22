# Side-Channel Proxy Interception Benchmark

Date: 2026-02-22  
Epic: `cc-dump-v78`

## Reproducible command

```bash
uv run python benchmarks/bench_side_channel_latency.py --runs 50 --json
```

## Scenario

- startup latency: `900ms`
- token/chunk delay: `18ms`
- chunks: `80`
- interception overhead: `2ms`

## Results

```json
{
  "summary": {
    "first_token_stdout_ms_mean": 2340.0,
    "first_token_intercept_ms_mean": 920.0,
    "first_token_delta_ms_mean": 1420.0,
    "total_stdout_ms_mean": 2340.0,
    "total_intercept_ms_mean": 2342.0,
    "total_delta_ms_mean": -2.0
  }
}
```

## Recommendation

- Keep proxy interception as the default side-channel observability path.
- Use stream-progress events for UI updates (first-token win is substantial in this model).
- Treat subprocess stdout as completion/backstop only, not primary timing source.

## Notes

- This benchmark is synthetic and deterministic.
- It is intended to evaluate collection-path timing behavior, not model quality.
