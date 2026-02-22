# Side-Channel Extracted Ideas And Foundation Plan

Date: 2026-02-22
Source transcript: `docs/side-channel/ORIGINAL-BRAINSTORMING.md`
Purpose: Convert raw brainstorming into concrete, durable, implementation-ready direction.

Detailed bucket planning docs:
- `docs/side-channel/buckets/INDEX.md`

## Non-Negotiable Constraints

- Use `claude -p` for side-channel generation so the feature works for subscription users and stays aligned with Claude Code usage patterns.
- Do not intercept, extract, or reuse API credentials for direct Anthropic API calls.
- Keep side-channel behavior opt-in via settings, with a working off path and fallback behavior.
- Development default is enabled (`true`) until the feature is stable; flip to disabled (`false`) before release.
- Keep side-channel data structurally separate from main conversation and HAR data, with explicit category separation if retained for debugging.
- Route widget-facing data through one consumer/dispatcher so UI blocks do not depend on transport details.
- Preserve isolation so wide refactors in unrelated app areas do not break side-channel internals.

// [LAW:single-enforcer] Side-channel eligibility and routing must be enforced at one boundary (dispatcher + side-channel router), not per-widget.
// [LAW:one-source-of-truth] One canonical side-channel pipeline should own enrichment state; all UI renderers consume derived outputs.
// [LAW:locality-or-seam] Side-channel code lives behind a seam so unrelated refactors do not cascade into this subsystem.

## Extracted Core Ideas

1. Side-channel inference lane:
Run dedicated `claude -p --model haiku --allowedTools ""` requests for low-latency enrichment tasks.

2. Sentinel-based request tagging:
Attach a unique marker to side-channel prompts so proxy/pipeline logic can identify and split traffic safely.

3. Real-time response tapping:
Read streaming side-channel responses while in transit through the proxy to reduce end-to-end latency versus waiting on subprocess completion formatting.

4. Cache-aware session strategy:
Investigate controlled reuse of cache-relevant session context while keeping local session state isolated from user session history.

5. Session safety guardrail:
Maintain a no-taint guarantee for user session history; if needed, duplicate local session data and isolate side-channel local IDs from user-visible session files.

6. Unified internal consumer:
Use a single internal data dispatcher that serves AI results or fallback results to downstream widgets.

7. Explicit fallback behavior:
When side-channel is disabled or fails, provide deterministic fallback summaries and keep UI fully functional.

8. Debug visibility without mixing:
Expose side-channel runs in existing cc-dump multi-session/HAR views with explicit category metadata so debugging is possible while accidental cross-contamination is structurally blocked.

// [LAW:dataflow-not-control-flow] Main and side-channel requests should pass through the same ordered stages; category metadata carries variability.
// [LAW:one-way-deps] Widgets depend on dispatcher contracts; dispatcher depends on side-channel transport; transport must not call back up into widgets.

## Product Feature Backlog (Ideas To Preserve)

- Turn summaries: summarize long assistant/tool responses in the UI.
- System prompt diff explanations: explain changes and rationale.
- Smart search: semantic retrieval over conversation content.
- Content classification: auto-tag turns by topic/intent.
- Running compaction summary: continuously maintain a compressed conversation state.
- User-shaped compaction: allow user-provided guidance for summary emphasis/exclusion.
- Context reset bootstrap: use approved compacted output to seed a fresh session later.

## Foundation MVP (Testing Harness)

Goal: Validate the full side-channel workflow with minimal UI surface before integrating into production blocks.

MVP UI:
- A simple modal dialog for development/testing.
- One button: "Summarize last 10 messages".
- A scrollable Markdown result area inside the modal.

MVP behavior:
- Reads last 10 messages from current context source.
- Sends one side-channel summarization request.
- Displays streamed/final summary result.
- Shows fallback result when side-channel is off or fails.
- Obeys settings toggle in real time.

// [LAW:verifiable-goals] MVP is complete only when the modal proves end-to-end request, routing, and fallback behavior with deterministic checks.

## Implementation Plan (Phased)

Phase 0: Research and invariants.
- Confirm precise `claude -p` behavior for `--resume` and persistence side effects.
- Validate sentinel design that survives transport but does not pollute output.
- Define explicit side-channel event category and filtering rules.
- Capture no-taint invariants in tests.

Phase 1: Core pipeline isolation.
- Implement/solidify side-channel manager boundary (subprocess ownership and lifecycle).
- Implement routing/classification boundary for side-channel traffic.
- Implement dispatcher as sole widget-facing consumer with fallback semantics.
- Ensure side-channel traffic cannot appear in main conversation stream by default.

Phase 2: Settings and control plane.
- Add/confirm opt-in setting wiring with functional on/off behavior.
- Keep default `true` for development builds.
- Ensure runtime toggling works without restart.

Phase 3: MVP modal.
- Add modal with summarize button and Markdown output.
- Wire to dispatcher API only (no direct transport usage in UI).
- Add loading, success, and error states.

Phase 4: Hardening and instrumentation.
- Add telemetry/debug hooks for side-channel latency and status.
- Add HAR metadata stamping for side-channel category/session/flag/cache counters.
- Add regression tests for separation, fallback, and no-taint guarantees.

// [LAW:behavior-not-structure] Tests should assert user-visible contracts (separation, fallback, output availability), not internal class wiring.

## Acceptance Criteria (Machine-Verifiable)

- Setting off:
Modal summary action returns fallback output with no side-channel subprocess invocation.

- Setting on:
Modal summary action returns AI output (or explicit AI error) and keeps UI responsive.

- Separation:
Side-channel requests/responses do not render as normal conversation turns in default views.

- Isolation:
No mutation of the original user session history during side-channel summarization flow.

- Dispatcher contract:
Widgets receive one normalized result shape regardless of source (`ai`, `fallback`, `error`).

- Observability:
Logs/metrics can identify side-channel requests and outcomes without exposing credentials.

## Debug Story And Segregation Model

Objective: make side-channel behavior diagnosable from live cc-dump surfaces without contaminating primary conversation data.

Segregation boundaries:
- Classification boundary:
Every request is classified once as `primary` or `side_channel` at ingress, using explicit side-channel markers/metadata.
- Routing boundary:
`primary` and `side_channel` traffic are sent to different internal streams; primary conversation views only subscribe to `primary`.
- Storage boundary:
Use the existing HAR pipeline and mark side-channel entries with explicit metadata (for example HAR `entry.comment` and/or an extension field like `_cc_dump.category = "side_channel"`). Do not create a parallel trace file format.
- Rendering boundary:
Primary timeline never renders side-channel runs; side-channel runs are inspected through existing cc-dump multi-session/lane and HAR views.
- Export boundary:
Primary export excludes side-channel by default; optional debug export can include side-channel explicitly.

// [LAW:single-enforcer] Classification/routing must happen in one pipeline boundary, not in each widget.
// [LAW:one-source-of-truth] Category is canonical metadata on each request/response envelope.
// [LAW:dataflow-not-control-flow] Both categories pass through the same ordered stages; category value controls sink selection.

HAR metadata to attach for side-channel debug visibility:
- `run_id` (UUID)
- `category` (`side_channel`)
- `origin_session_id` (user-facing source session id, if relevant)
- `local_side_session_id` (if generated)
- `prompt_hash` (debug correlation, not raw prompt by default)
- `started_at`, `first_token_ms`, `completed_ms`
- `status` (`ok` | `timeout` | `error` | `cancelled`)
- `model`, `command_flags`
- `cache_created_tokens`, `cache_read_tokens` (if available)
- `output_excerpt` (bounded, redacted)

// [LAW:one-source-of-truth] HAR remains the canonical debug artifact; side-channel data is metadata on HAR entries, not a second trace format.
// [LAW:locality-or-seam] Debugging remains inside existing cc-dump surfaces; no separate side-channel mini-application in roadmap.

Debug workflow (day-to-day):
1. Trigger side-channel request from the MVP UI.
2. Switch to the side-channel lane/session in cc-dump.
3. Jump to the linked HAR entry and verify:
- classified as `side_channel`
- CLI flag profile used
- cache counters indicate expected behavior
- no primary turn record was created from this request
4. Re-run with another flag profile (`resume+fork`, `no-persistence`) and compare HAR metadata/counters.

Multi-session debugging scenario:
1. Main session stays focused on user traffic.
2. Side-channel runs are opened in a dedicated side-channel lane/session view.
3. Operator can switch between lanes to compare:
- side-channel HAR entries
- primary session entries
- cache counters and latency across runs
4. No lane mixing: side-channel lane data never appears in the main session lane.

Leak-prevention invariants:
- Side-channel run IDs are never reused as primary conversation IDs.
- No side-channel record can be attached to primary turn objects.
- No side-channel event reaches the primary event subscriber queue.
- Failure mode defaults to fallback output, not mixed output.

## Claude CLI Session Flag Strategy

Validated from local `claude --help` (2026-02-22):
- `--session-id <uuid>`: use a specific session id.
- `--fork-session`: when resuming/continuing, create a new session id instead of reusing the original.
- `--no-session-persistence`: in `--print` mode, do not save sessions to disk.

// [LAW:one-type-per-behavior] Session strategy should be one configurable policy type with different flag instances, not separate ad hoc code paths.

Recommended strategy profiles:
- `ephemeral_default` (safest baseline):
`claude -p --model haiku --tools "" --output-format stream-json --include-partial-messages --no-session-persistence`
- `cache_probe_resume` (cache-hit fork strategy):
`claude -p --model haiku --tools "" --output-format stream-json --include-partial-messages --resume <session-id> --fork-session`
- `isolated_fixed_id` (deterministic local correlation):
`claude -p --model haiku --tools "" --output-format stream-json --include-partial-messages --session-id <generated-uuid> --no-session-persistence`

Notes:
- Use `--tools ""` (or equivalent deny policy) to keep side-channel requests single-turn and inert.
- Treat profile selection as configuration through one dispatcher-side strategy field.
- Keep request-body rewrite as optional last-resort strategy, not default.
- Cache-hit intention is centered on `--resume <session-id> --fork-session`; debug must confirm this with observed cache-read counters.

Experiment matrix (must pass before promoting cache profile):
1. `--resume + --fork-session`:
Verify whether cache-read tokens increase and whether original session history remains unchanged.
2. `--resume + --fork-session + --no-session-persistence`:
Verify whether resume still benefits cache while writing no local session files.
3. `--session-id + --no-session-persistence`:
Verify deterministic correlation and no disk persistence.
4. all profiles:
Verify side-channel runs stay segregated from primary timeline/HAR by automated tests.

// [LAW:verifiable-goals] Each profile requires deterministic checks: cache counters, file persistence, and stream segregation assertions.

## Deferred Proposal (Not On Roadmap)

Proposal:
- A separate side-channel trace file format/store independent from HAR.
- A dedicated side-channel debug modal/panel with custom run list/detail UI.

Status:
- Deferred / not planned.

Reason:
- cc-dump already emits HAR as the canonical low-level artifact.
- A second format duplicates debugging sources and increases maintenance cost.
- A dedicated side-channel debug UI duplicates capabilities that should live in core cc-dump multi-session/HAR debugging workflows.
- Side-channel debugging requirements can be met by HAR metadata + existing cc-dump session/lane inspection.

## Idea Generation As A First-Class Workstream

- Keep this document as the durable, curated idea ledger.
- Add a dated "Idea Candidate" entry for every new side-channel concept before implementation.
- Require each candidate to include user value, risk, and one verifiable success criterion.
- Promote candidates to implementation only after they satisfy foundation constraints above.

// [LAW:one-source-of-truth] This file is the canonical curated plan; raw transcript remains historical source material only.
