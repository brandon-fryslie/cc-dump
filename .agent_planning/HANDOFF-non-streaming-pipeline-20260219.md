# Handoff: Non-Streaming Pipeline Unification & Auto-Resume Fix

**Created**: 2026-02-19
**Status**: in-progress (partially implemented, 1 test failure remaining)
**Branch**: `bmf_fix_missing_assistant_header`

---

## Objective

Fix two related issues: (1) Claude auto-resume doesn't work because session_id was never captured during HAR replay, and (2) non-streaming HTTP responses were silently dropped by the proxy. Both stem from the replay path bypassing the normal event pipeline.

## Current State

### What's Been Done

1. **Session ID sourced from formatting state, not blocks** — `event_handlers.py` no longer reads `block.session_id` from `NewSessionBlock`. The app reads `self._state["current_session"]` directly after every event handler call (`app.py` ~line 567). The `NewSessionBlock` import was removed from event_handlers, `new_session_id` removed from `AppState` TypedDict.

2. **Replay now uses the event pipeline** — `_process_replay_data()` in `app.py` now calls `har_replayer.convert_to_events()` → feeds each event through `_handle_event_inner()`. This means replay gets session detection, stats refresh, and all other post-processing for free.

3. **New `ResponseNonStreamingEvent`** — Added to `event_types.py` with `PipelineEventKind.RESPONSE_NON_STREAMING`. Carries `status_code`, `headers`, `body` (the complete JSON response).

4. **`handle_response_non_streaming` handler** — Added to `event_handlers.py`. Calls `format_response_headers()` + `format_complete_response()`, stamps session_id, calls `conv.add_turn()`, refreshes stats/panels.

5. **Proxy emits events for non-streaming responses** — The `else` branch in `proxy.py` (~line 331) now parses the response JSON and emits `ResponseNonStreamingEvent` instead of silently passing bytes through.

6. **`har_replayer.convert_to_events()` simplified** — No longer synthesizes fake SSE events. Returns 3 events: `RequestHeadersEvent`, `RequestBodyEvent`, `ResponseNonStreamingEvent`. Massive code reduction (~120 lines of SSE synthesis removed).

7. **`format_complete_response` returns flat blocks** — Removed the `ResponseMessageBlock` wrapper so output matches the streaming path's finalized structure (flat list of `StreamInfoBlock`, `TextDeltaBlock`, `StreamToolUseBlock`, `StopReasonBlock`).

8. **Deleted tests that tested implementation details** — Removed `test_e2e_record_replay.py` (606 lines) and `test_har_replay_integration.py` (348 lines). These did isinstance dispatch on specific event types (ResponseSSEEvent, MessageStartEvent, etc.) to validate internal structure rather than behavior.

9. **Diagnostic logging added** — `app.py` logs "Session detected: {id}" when session changes and "Launching claude: config=... session_id=... extra_args=..." on launch.

### What Remains

1. **One failing test**: `tests/test_event_types.py::TestEnums::test_pipeline_event_kind_values` asserts `len(PipelineEventKind) == 8`, now 9 with `RESPONSE_NON_STREAMING`. Fix: update assertion to 9.

2. **Full test suite not yet run to completion** — The enum test blocks `-x` from continuing. After fixing it, run `uv run pytest tests/ -x` to verify no other breakage.

3. **`ResponseMessageBlock` is now dead code** — Nothing creates it. It still exists in `formatting.py` (class definition), `rendering.py` (renderer registration), `dump_formatting.py` (isinstance check). Should be removed.

4. **Replacement tests needed** — The deleted e2e tests enforced "zero divergence between live and replay." New tests should verify behavior (e.g., "replay produces visible content", "session_id is captured during replay") without isinstance checks on internal event types.

5. **Beads ticket for architectural vision** — User requested a ticket describing the architecturally correct long-term approach: the pipeline should speak complete messages, SSE is a transport detail reassembled at the proxy boundary, streaming UX is a rendering concern not a pipeline concern.

6. **User has NOT tested auto-resume since the replay fix** — The session detection fix was the main goal. Needs manual verification: start cc-dump with replay, press `c` to launch claude, quit claude, press `c` again — should pass `--resume <session_id>`.

## Key Decisions Made

| Decision | Rationale |
|----------|-----------|
| Read session_id from `state["current_session"]` not blocks | Blocks are rendering artifacts, not data sources (user directive) |
| Session detection in app's `_handle_event_inner`, not event handler | App owns `_state`, no side-channel needed through `app_state` dict |
| `ResponseNonStreamingEvent` (not `RESPONSE_COMPLETE`) | User chose naming |
| Delete rather than fix divergence tests | Tests were asserting implementation structure (isinstance checks), not behavior |
| `format_complete_response` returns flat blocks | Must match streaming path's finalized output — one block structure regardless of transport |

## Key Files Modified

- `src/cc_dump/event_types.py` — Added `RESPONSE_NON_STREAMING`, `ResponseNonStreamingEvent`
- `src/cc_dump/proxy.py` — Non-streaming branch now emits events
- `src/cc_dump/tui/event_handlers.py` — Removed block-based session detection, added `handle_response_non_streaming`
- `src/cc_dump/tui/app.py` — Session detection from `_state`, replay via event pipeline, removed `AppState.new_session_id`
- `src/cc_dump/har_replayer.py` — Simplified to emit `ResponseNonStreamingEvent`
- `src/cc_dump/formatting.py` — `format_complete_response` returns flat list (no `ResponseMessageBlock` wrapper)
- `tests/test_har_replayer.py` — Simplified to test 3-event output contract

## Files Deleted

- `tests/test_e2e_record_replay.py` — 606 lines, isinstance-based structural comparison
- `tests/test_har_replay_integration.py` — 348 lines, isinstance-based event processing

## Known Gotchas

- `_handle_event_inner` returns early if `conv` or `stats` widgets not found. During replay in `on_mount`, widgets should exist, but verify.
- The streaming path stamps `session_id` on response blocks in handlers (`handle_response_headers`, `handle_response_event`). The non-streaming handler does the same. These are duplicated patterns — a future cleanup could centralize session stamping.
- `format_complete_response` uses `TextDeltaBlock` (not `TextContentBlock`) for text content. This matches what streaming produces before finalization. `finalize_streaming_turn` consolidates `TextDeltaBlock` → `TextContentBlock`. For non-streaming via `add_turn`, there's no finalization step — check if this causes rendering differences.

## Immediate Next Steps

1. Fix `test_event_types.py` — change `assert len(PipelineEventKind) == 8` to `== 9`
2. Run full test suite: `uv run pytest tests/ -x`
3. Remove dead `ResponseMessageBlock` class and all references
4. Create beads ticket for long-term pipeline architecture
5. Write behavioral replacement tests for the deleted e2e tests
6. Manual test: replay → auto-resume workflow
