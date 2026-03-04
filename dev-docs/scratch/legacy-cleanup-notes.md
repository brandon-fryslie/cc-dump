# Legacy / Complexity Cleanup Notes

Date: 2026-03-03
Scope: named-session cleanup + HAR layout migration

## Addressed In This Pass
- Removed cc-dump "named session" CLI/runtime plumbing (`--session`, `session_name` fields, session subtitle wiring).
- Switched default HAR write path to provider-only layout:
  - `~/.local/share/cc-dump/recordings/ccdump-<provider>-<timestamp>-<shortid>.har`
- Removed `session_name` from recordings metadata and table output.
- Removed stale `RecordingInfo.session_id` derivation from HAR filenames.
- Simplified recording provider detection to derive from canonical filename and HAR metadata.
- Removed runtime layout migration from app startup in favor of one-time operational migration.
- Executed one-time local migration on 2026-03-04:
  - moved 223 HAR files into flat layout
  - resulting inventory: 223 flat files, 0 nested files

## Additional Legacy / Unaligned Areas Observed
- `src/cc_dump/tui/app.py`
  - App still owns both:
    - Claude runtime session identity (`_session_id`)
    - UI tab/session routing (`_session_domain_stores`, `_session_conv_ids`, `_session_tab_ids`, `_request_session_keys`)
  - This is a lot of orchestration in one class and makes lifecycle/hot-reload behavior hard to reason about.

- `src/cc_dump/tui/app.py` + `src/cc_dump/tui/action_handlers.py`
  - `show_logs` / `show_info` are Textual reactives while most other UI visibility uses SnarFX view-store state.
  - This split state model is inconsistent and invites drift.

- `src/cc_dump/tui/panel_renderers.py`
  - `info_panel_rows()` still has backward-compat fallback branches for older info payload shapes.
  - Useful now, but should be dropped once all callers are guaranteed on the normalized `providers` payload.

- `src/cc_dump/ai/side_channel_marker.py`
  - Marker parser still supports legacy key fallback:
    - `source_provider` <- `source_session_id`
  - This keeps backward compatibility for old HAR files but adds schema ambiguity.

- `src/cc_dump/tui/settings_launch_controller.py`
  - Auto-resume logic still depends on `_active_resume_session_id()` from app-level session context.
  - Worth validating whether this should be a dedicated boundary/service rather than app method reach-through.

- `src/cc_dump/tui/search_controller.py`
  - Search UI updates are manually pushed from many call sites (`update_search_bar()` imperative fanout).
  - Candidate for a single SnarFX projection path to reduce scatter and mismatch risk.

## Suggested Follow-Up Sequence
1. Unify `show_logs`/`show_info` under view-store state.
2. Remove `source_session_id` marker fallback after compatibility window.
3. Split session routing responsibilities out of `CcDumpApp` into a focused coordinator.
