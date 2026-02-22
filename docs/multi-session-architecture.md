# Multi-Session Architecture Proposal

## Scope
This proposal defines how `cc-dump` moves from one active conversation stream to multiple first-class sessions (live and replay) without breaking existing single-session workflows.

## Current Constraints
- Runtime state assumes one active orchestrator session (`state["current_session"]`).
- `DomainStore` owns one append-only completed stream plus active request streams.
- `ConversationView` renders one `DomainStore` projection at a time.
- HAR recordings are already session-organized on disk, but runtime replay loads one HAR at a time.

## Goals
- Support multiple independent conversation sessions in one app process.
- Preserve request-scoped SSE correctness inside each session.
- Keep existing single-session behavior as default path.
- Keep replay/live semantics aligned.

## Non-Goals
- Cross-session token capacity prediction (no authoritative upstream capacity feed).
- Merging distinct sessions into one synthetic conversation timeline.

## Proposed Model

### Session Identity
- Canonical runtime key: `session_key`.
- `session_key` format: `{source}:{session_id}` where:
  - `source` is `live` or `replay`.
  - `session_id` is Claude session id when present, otherwise deterministic fallback (`request_id` lineage bucket).

`// [LAW:one-source-of-truth] session_key is the only runtime session identity.`

### Session Runtime State
- Introduce `SessionRuntime` aggregate:
  - `domain_store`
  - `stream_registry`
  - `view_store_slice` (session-local filters/search/follow)
  - replay metadata (`har_path`, `loaded_at`, etc.)
- App-level registry: `session_key -> SessionRuntime`.
- App-level active pointer: `active_session_key`.

`// [LAW:locality-or-seam] session registry isolates session state from global app wiring.`

### Data Ownership
- Keep `DomainStore` and `StreamRegistry` unchanged as per-session owners.
- Do not share mutable block lists across sessions.

`// [LAW:no-shared-mutable-globals] no cross-session mutable singleton stores.`

## UI/UX Proposal

### Session Switcher
- Add a top-level session switch strip (tab/chip model) above `ConversationView`.
- Each tab label:
  - session display name (`session_id` short or HAR filename)
  - live/replay indicator
  - unread/live-dot state

### View Behavior
- `ConversationView` mounts against active `SessionRuntime.domain_store`.
- Switching session swaps view binding; no data copy.
- Filters/search/follow are session-local and restored per tab.

### Minimal Interaction Set
- Next/prev session keybinds.
- Command palette:
  - `Switch session`
  - `Open replay as new session`
  - `Close replay session`

## Replay + Live Compatibility
- Live proxy events routed to session runtime by `session_key` classifier.
- Replay loader can:
  - open as standalone session tab
  - optionally attach to existing matching session key.
- Sidecar UI state becomes per-session (`<har>.ui.json` already compatible with this model).

## Side-Channel Debug Lane (Integration)

- Add `live:side-channel:<source-session-id>` session keys for side-channel runs.
- Route side-channel-classified requests into that lane, never into the main `live:<session-id>` lane.
- Reuse existing HAR/event pipeline; mark side-channel entries in HAR metadata (category + run/session flags).
- Expose side-channel lane in session switcher for low-level inspection while preserving main-session cleanliness.

`// [LAW:single-enforcer] Session classifier is the only place that assigns side-channel vs primary lanes.`
`// [LAW:one-source-of-truth] Side-channel lane identity derives from session_key, not ad hoc widget state.`
`// [LAW:one-way-deps] Conversation/debug widgets consume lane data; they do not decide routing.`

## Implementation Plan

1. Session registry scaffold
- Add `SessionRuntime` + app session registry.
- Keep single-session compatibility by auto-creating default `live:*` session.

2. Session-aware routing
- Route all event handlers through session lookup.
- Instantiate per-session `DomainStore` + `StreamRegistry`.

3. UI switcher integration
- Add session switch strip + active session pointer.
- Rebind `ConversationView` on switch.

4. Replay multi-open
- `--replay` opens in dedicated session runtime.
- Add command to open additional HAR sessions while app runs.

5. Persistence
- Persist last active session + per-session UI slices.
- Rehydrate on resume.

## Verifiable Acceptance Criteria
- Opening two sessions keeps their turns/streams fully isolated.
- Switching tabs never interleaves block lists between sessions.
- Per-session filters/search/follow restore exactly after switching away and back.
- Replay and live sessions can coexist simultaneously.
- Existing single-session launch path works unchanged.
- Side-channel requests appear only in side-channel lanes and never in primary lanes.

## Risks and Mitigations
- Risk: session routing ambiguity for missing session ids.
  - Mitigation: deterministic fallback buckets and explicit unknown-session tab.
- Risk: memory growth with many loaded sessions.
  - Mitigation: cap inactive replay sessions and unload policy.
- Risk: UI complexity explosion.
  - Mitigation: keep one canonical switcher model; no split-view in first phase.

## Migration Strategy
- Phase-gated rollout:
  - Phase 1: internal registry + single visible session.
  - Phase 2: visible session switcher.
  - Phase 3: multi-open replay/live.
- No schema migration required for existing HAR files.
