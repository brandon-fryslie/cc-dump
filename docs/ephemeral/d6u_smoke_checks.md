# d6u Smoke Checks (M1-M4)

This runbook replaces the old manual-only d6u smoke checklist with a deterministic test suite.

## Command

```bash
just smoke-d6u
```

## Mapping

| Manual ID | Automated test |
|---|---|
| M1 Live proxy analytics | `test_m1_live_proxy_analytics_budget_tokens_present` |
| M2 Live proxy HAR capture validity | `test_m2_live_proxy_har_capture_valid_entry` |
| M3 Replay parity vs live | `test_m3_replay_parity_matches_live_analytics_projection` |
| M4 tmux auto-zoom request/end_turn | `test_m4_tmux_auto_zoom_request_then_end_turn` |

## Notes

- These tests intentionally exercise the same response-side event contracts used in production.
- The suite runs without external Claude traffic or a real tmux session.
