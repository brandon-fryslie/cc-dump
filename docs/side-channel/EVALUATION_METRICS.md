# Side-Channel Evaluation Metrics

Canonical thresholds are defined in `src/cc_dump/side_channel_eval_metrics.py`.

`// [LAW:one-source-of-truth] CI/local gates read one threshold map for all purposes.`

## Gate model

- Each purpose has deterministic checks in `src/cc_dump/side_channel_eval.py`.
- Each purpose must meet `min_pass_rate` from `PURPOSE_MIN_PASS_RATE`.
- Current baseline is strict: every purpose must pass all checks (`1.0`).

## Purposes covered

- `block_summary`
- `decision_ledger`
- `checkpoint_summary`
- `action_extraction`
- `handoff_note`
- `incident_timeline`
- `conversation_qa`
- `segregation`
- `budget_guardrails`

## CI command

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m cc_dump.side_channel_eval --check --output .artifacts/side_channel_eval.json
```
