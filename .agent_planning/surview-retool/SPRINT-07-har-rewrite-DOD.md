# Definition of Done: Sprint 7 - HAR Rewrite

## Exit Criteria
1. HAR recording captures generic HTTP request/response pairs
2. HAR replay emits generic events (no Claude SSE synthesis)
3. reconstruct_message_from_events() and convert_to_events() do not exist
4. End-to-end: proxy request → HAR record → HAR replay → TUI display

## Verification
```bash
# Record
uv run surview --port 8080 &
curl -x http://127.0.0.1:8080 https://httpbin.org/get  # or via reverse proxy
# Check recording file exists and contains valid HAR

# Replay
uv run surview --replay ~/.local/share/surview/recordings/latest.har
# Verify request/response displays in TUI

grep -rn "reconstruct_message\|convert_to_events\|message_start\|content_block" src/surview/har_recorder.py src/surview/har_replayer.py
# Should return zero hits
```
