# AI Workbench Feature Removal Spec

Date: 2026-03-07

Scope:
- User-stated keepers: `Handoff Draft`
- User-stated tolerated POC: `Ask Scoped Q&A` / "ask a message about something"
- This document specs everything else currently bundled into the AI Workbench surface or its backend support code.

## Executive Read

If the product intent is "keep handoff, keep Q&A as a lightweight POC, remove the rest," the main cuts are:

1. `Summarize Recent`
2. `Action Extraction`
3. `Apply Review`
4. `beads` action-item issue creation
5. `Utility Runner`
6. all five registered utility subfeatures
7. hidden checkpoint backend
8. summary cache if summary goes away
9. duplicate results presentation if the sidebar alone is enough

The biggest removal win is the action-extraction family. The cleanest low-risk cut is the utility family.

## Current Workbench Surface

Panel-visible controls in [side_channel_panel.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_panel.py):
- `Summarize Recent`
- `Estimate Q&A`
- `Ask Scoped Q&A`
- `Extract Actions`
- `Apply Review`
- `Handoff Draft` (currently placeholder-wired)
- `Run Utility`

Hidden backend-only workbench capabilities in [data_dispatcher.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/data_dispatcher.py):
- checkpoint creation
- checkpoint snapshot listing
- checkpoint diff rendering
- accepted action-item snapshot
- summary cache

## Feature Specs

### 1. Summarize Recent
- Status: panel-visible
- Primary files:
  - [side_channel_panel.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_panel.py)
  - [side_channel_controller.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_controller.py)
  - [data_dispatcher.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/data_dispatcher.py)
  - [summary_cache.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/summary_cache.py)
- Complexity: `MEDIUM`
- Why: It has its own chip, controller path, dispatcher path, prompt path, usage tracking, and a dedicated persistent cache.
- Value relative to your stated goals: low. It overlaps with handoff and with the Q&A POC, and it is not the feature you care about.
- Removal verdict: `REMOVE`
- Removal notes:
  - delete the `Summarize Recent` control and controller action
  - delete `summarize_messages()` and prompt-prep helpers if nothing else consumes them
  - delete `SummaryCache` if this is the only remaining consumer

### 2. Action Extraction
- Status: panel-visible
- Primary files:
  - [side_channel_panel.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_panel.py)
  - [side_channel_controller.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_controller.py)
  - [data_dispatcher.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/data_dispatcher.py)
  - [action_items.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/action_items.py)
- Complexity: `HIGH`
- Why: It introduces batch state on `app`, parsing of structured AI output, review staging, persistent accepted items, and source-link bookkeeping.
- Value relative to your stated goals: low. It is a separate workflow from handoff and not needed for a basic "ask about the conversation" POC.
- Removal verdict: `REMOVE`
- Removal notes:
  - remove `Extract Actions` control and extraction controller flow
  - delete action-item parsing/staging store if review is also removed
  - remove `app._sc_action_batch_id` and `app._sc_action_items` state if no other consumer remains

### 3. Apply Review
- Status: panel-visible, but only meaningful after `Extract Actions`
- Primary files:
  - [side_channel_panel.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_panel.py)
  - [side_channel_controller.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_controller.py)
  - [data_dispatcher.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/data_dispatcher.py)
  - [action_items.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/action_items.py)
- Complexity: `HIGH`
- Why: It adds secondary review UI, index parsing, validation, accept/reject semantics, and mutation of the staged item batch.
- Value relative to your stated goals: very low. It only exists to complete the action-extraction workflow.
- Removal verdict: `REMOVE WITH ACTION EXTRACTION`
- Removal notes:
  - this should not survive independently
  - once action extraction is gone, this feature and its controller path should be removed as a family

### 4. beads Issue Creation for Accepted Actions
- Status: secondary option inside `Apply Review`
- Primary files:
  - [side_channel_panel.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_panel.py)
  - [side_channel_controller.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_controller.py)
  - [data_dispatcher.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/data_dispatcher.py)
  - [action_items_beads.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/action_items_beads.py)
- Complexity: `MEDIUM`
- Why: It shells out to `bd`, adds a side-effect boundary, and only exists as a subfeature of accepted action items.
- Value relative to your stated goals: none.
- Removal verdict: `REMOVE WITH ACTION FAMILY`
- Removal notes:
  - remove the checkbox and the beads hook path
  - delete [action_items_beads.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/action_items_beads.py) if action review is removed

### 5. Utility Runner
- Status: panel-visible
- Primary files:
  - [side_channel_panel.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_panel.py)
  - [side_channel_controller.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_controller.py)
  - [data_dispatcher.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/data_dispatcher.py)
  - [utility_catalog.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/utility_catalog.py)
- Complexity: `MEDIUM`
- Why: The runner itself is not huge, but it introduces a second mini-product inside the workbench: registry, select input, prompt builder, fallback logic, and result rendering.
- Value relative to your stated goals: low. It is outside handoff and outside the Q&A POC.
- Removal verdict: `REMOVE`
- Removal notes:
  - remove the utility launcher section from the panel
  - delete dispatcher utility methods if no other caller exists
  - delete the utility registry and fallback behaviors as a single cut

### 6. Utility: Turn Title
- Status: utility subfeature
- Primary file: [utility_catalog.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/utility_catalog.py)
- Complexity: `LOW`
- Removal verdict: `REMOVE WITH UTILITY RUNNER`
- Notes: low standalone complexity, but no value if utilities are not a product goal

### 7. Utility: Glossary Extract
- Status: utility subfeature
- Primary file: [utility_catalog.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/utility_catalog.py)
- Complexity: `LOW`
- Removal verdict: `REMOVE WITH UTILITY RUNNER`
- Notes: another experimental utility with no dependency outside the utility registry

### 8. Utility: Recent Changes Digest
- Status: utility subfeature
- Primary file: [utility_catalog.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/utility_catalog.py)
- Complexity: `LOW`
- Removal verdict: `REMOVE WITH UTILITY RUNNER`
- Notes: overlaps conceptually with `Summarize Recent`

### 9. Utility: Intent Tags
- Status: utility subfeature
- Primary file: [utility_catalog.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/utility_catalog.py)
- Complexity: `LOW`
- Removal verdict: `REMOVE WITH UTILITY RUNNER`
- Notes: classification helper, not part of handoff or Q&A

### 10. Utility: Search Query Terms
- Status: utility subfeature
- Primary file: [utility_catalog.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/utility_catalog.py)
- Complexity: `LOW`
- Removal verdict: `REMOVE WITH UTILITY RUNNER`
- Notes: retrieval helper, not part of handoff or Q&A

### 11. Purpose Usage Summary / Usage Telemetry Display
- Status: panel-visible support feature
- Primary files:
  - [side_channel_panel.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_panel.py)
  - [side_channel_controller.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/side_channel_controller.py)
  - analytics store integration
- Complexity: `LOW`
- Why: It is mostly presentation state, but it widens the workbench surface and reinforces the "multi-tool dashboard" shape.
- Value relative to your stated goals: low.
- Removal verdict: `SIMPLIFY OR REMOVE`
- Removal notes:
  - if the panel becomes handoff + Q&A only, replace this with a minimal status line or drop it completely

### 12. Workbench Results Tab (Full-Width Mirror of Sidebar Output)
- Status: support feature, separate presentation path
- Primary file: [workbench_results_view.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/tui/workbench_results_view.py)
- Complexity: `MEDIUM`
- Why: It duplicates the same result payload into a second rendering path (`sc:*` sidebar state and `workbench:*` full-width state).
- Value relative to your stated goals: unclear. Handoff may still benefit from a wide markdown surface, but the duplication is architectural overhead.
- Removal verdict: `SIMPLIFY`
- Removal notes:
  - if handoff remains markdown-heavy, keep one result surface only
  - preferred direction: choose either sidebar preview only or full-width results only, not both

### 13. Checkpoint Summaries and Checkpoint Diff
- Status: backend-only, not surfaced in the current panel controls
- Primary files:
  - [data_dispatcher.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/data_dispatcher.py)
  - [checkpoints.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/checkpoints.py)
- Complexity: `MEDIUM`
- Why: There is a full artifact/store/diff flow for checkpoints, but no corresponding current workbench control in the panel.
- Value relative to your stated goals: none.
- Removal verdict: `REMOVE`
- Removal notes:
  - this is the cleanest hidden backend cut after utilities
  - delete the dispatcher checkpoint methods and the checkpoint artifact/store module if no external caller exists

### 14. Summary Cache
- Status: backend-only support feature
- Primary file: [summary_cache.py](/Users/bmf/.codex/worktrees/71ca/cc-dump/src/cc_dump/ai/summary_cache.py)
- Complexity: `LOW`
- Why: It exists only to optimize `Summarize Recent`.
- Value relative to your stated goals: none if summarization is removed.
- Removal verdict: `REMOVE WITH SUMMARIZE RECENT`
- Removal notes:
  - if `Summarize Recent` goes away, this should go away too

## Recommended Keep / Remove Target

### Keep
- `Handoff Draft`
- `Ask Scoped Q&A`

### Probably collapse
- `Estimate Q&A`
  - Complexity: `LOW`
  - Recommendation: fold it into `Ask Scoped Q&A` as inline preflight instead of keeping a separate chip

### Remove
- `Summarize Recent`
- `Action Extraction`
- `Apply Review`
- `beads` issue creation
- `Utility Runner`
- all five utility subfeatures
- checkpoint backend
- summary cache

### Simplify if handoff stays
- full-width `Workbench Results` duplication
- usage telemetry display

## Removal Priority

1. Utility Runner + utility catalog
2. Checkpoint backend
3. Summarize Recent + summary cache
4. Action Extraction + Apply Review + beads bridge
5. Duplicate results surface / usage telemetry simplification

Reason:
- utilities and checkpoints are isolated and cheap to cut
- summarize is broader but still mostly self-contained
- action extraction is the most entangled removal and should be done after the smaller families are gone
