# Complexity Reduction Roadmap (Top Priority)

**Date**: 2026-03-01  
**Status**: Active  
**Branch baseline**: `origin/master` (fresh branch from latest master)  
**Priority**: P0 until completion

## 1) Objective

Reduce architectural and implementation complexity without product regressions, with work explicitly partitioned so multiple streams can execute in parallel.

## 2) Master Baseline (Measured at Start)

- Python LOC (`src/cc_dump`): `29,814`
- Layer split:
  - `tui`: `16,432` LOC
  - `core`: `3,249` LOC
  - `app`: `2,559` LOC
  - `pipeline`: `2,553` LOC
  - `ai`: `2,702` LOC
  - `io`: `842` LOC
  - `experiments`: `696` LOC
  - `root_modules` (`src/cc_dump/*.py`): `781` LOC
- Highest complexity hotspots (radon cc):
  - `cli.main`: 69
  - `tui.dump_formatting.write_block_text`: 54
  - `tui.rendering._render_block_tree`: 52
  - `hot_reload_controller._replace_all_widgets_inner`: 34
  - `core.formatting.format_openai_request`: 33
  - `pipeline.response_assembler._reconstruct_openai_message`: 32
  - `analytics_store.get_dashboard_snapshot`: 31
  - `pipeline.proxy._proxy`: 29
  - `tui.rendering._render_region_parts`: 28
  - `core.formatting.format_request`: 24

## 3) Non-Negotiable Constraints

- `// [LAW:one-source-of-truth]` Canonical state lives in one place; all mirrors are derived.
- `// [LAW:single-enforcer]` Cross-cutting rules are enforced at one boundary only.
- `// [LAW:one-way-deps]` No upward dependency calls; no new cycles.
- `// [LAW:dataflow-not-control-flow]` Replace branching mode logic with data-driven dispatch/config.
- `// [LAW:verifiable-goals]` Every milestone has measurable pass/fail criteria and automated checks.

## 4) Program Structure (Parallel Workstreams)

This program is intentionally split into four parallel streams with clear ownership boundaries:

### Stream A: Rendering + Formatting Decomposition

**Scope**
- `src/cc_dump/tui/rendering.py`
- `src/cc_dump/core/formatting.py`
- `src/cc_dump/tui/dump_formatting.py`

**Goal**
- Break monolithic render/format/export dispatch into composable registries and module slices.

**Target outcomes**
- `rendering.py` reduced below `3,000` LOC.
- `_render_block_tree` reduced to CC `<= 20`.
- `formatting.py` reduced below `1,300` LOC.
- `write_block_text` reduced to CC `<= 15`.

### Stream B: App Orchestration + TUI Control Plane

**Scope**
- `src/cc_dump/tui/app.py`
- `src/cc_dump/tui/action_handlers.py`
- `src/cc_dump/tui/hot_reload_controller.py`
- `src/cc_dump/tui/search_controller.py`

**Goal**
- Turn `CcDumpApp` into thin composition root, with extracted runtime controllers.

**Target outcomes**
- `app.py` reduced below `1,700` LOC.
- `action_sc_action_apply_review` reduced to CC `<= 12`.
- `on_mount` reduced to CC `<= 10`.
- `_replace_all_widgets_inner` reduced to CC `<= 20`.

### Stream C: Proxy/CLI Runtime Simplification

**Scope**
- `src/cc_dump/cli.py`
- `src/cc_dump/pipeline/proxy.py`
- `src/cc_dump/pipeline/response_assembler.py`
- `src/cc_dump/pipeline/har_replayer.py`

**Goal**
- Collapse mode/branch explosion into a single resolved runtime config and uniform startup path.

**Target outcomes**
- `cli.main` reduced to CC `<= 20`.
- `proxy._proxy` reduced to CC `<= 15`.
- `_reconstruct_openai_message` reduced to CC `<= 18`.
- No behavior changes to live/replay parity tests.

### Stream D: AI Workbench + Analytics Modularization

**Scope**
- `src/cc_dump/ai/data_dispatcher.py`
- `src/cc_dump/tui/side_channel_panel.py`
- `src/cc_dump/app/analytics_store.py`

**Goal**
- Split workbench use-cases into command modules and reduce dispatcher orchestration density.

**Target outcomes**
- `data_dispatcher.py` reduced below `500` LOC.
- `analytics_store.get_dashboard_snapshot` reduced to CC `<= 14`.
- Side-channel action flow remains behavior-compatible (all current tests pass).

## 5) Dependency Graph (What Can Run In Parallel)

### Immediate Parallel Start

- Stream A can start immediately.
- Stream B can start immediately.
- Stream C can start immediately.
- Stream D can start immediately.

### Coordination Seams (to avoid collisions)

- Shared seam 1: block type/render registry contracts  
  - Owner: Stream A  
  - Consumers: Streams B and D
- Shared seam 2: app wiring interfaces  
  - Owner: Stream B  
  - Consumers: Streams A and D
- Shared seam 3: provider/runtime config model  
  - Owner: Stream C  
  - Consumers: Stream B

`// [LAW:locality-or-seam]` Any cross-stream touchpoint must first define/land seam interfaces, then refactor behind that seam.

## 6) Milestones

### Milestone M1: Seams + Metrics Guardrails (Week 1)

- Land module/interface seams for all four streams.
- Add CI complexity reporting script (radon snapshot + LOC snapshot).
- Update CI test workflow to run the full pytest suite.
- Freeze baseline behavior tests for touched features.

**Exit criteria**
- Seams merged with no functional behavior changes.
- Metrics report generated in CI artifact.
- Full test suite passes in CI (`uv run pytest`).

### Milestone M2: Monolith Extraction Pass (Weeks 2-3)

- Stream A extracts rendering/formatting/export registries.
- Stream B extracts app runtime controllers.
- Stream C extracts runtime config + startup orchestrator.
- Stream D extracts command handlers from dispatcher.

**Exit criteria**
- Each stream lands at least one major extraction with tests.
- No net increase in top-10 complexity hotspots.
- All stream PRs rebased and green.

### Milestone M3: Complexity Burn-Down (Weeks 4-5)

- Target all remaining CC > 20 functions in scoped files.
- Replace branch-heavy code with dispatch tables/state maps where valid.
- Remove dead/duplicative handlers and unify single-enforcer boundaries.

**Exit criteria**
- No function in scoped files above CC 20, except explicitly waived with doc rationale.
- LOC and complexity targets in Section 4 met or formally waived.
- No test regressions.

### Milestone M4: Stabilization + Lock-In (Week 6)

- Add regression tests for newly extracted seams.
- Add architecture docs for new boundaries.
- Cleanup deferred compatibility shims and temporary adapters.

**Exit criteria**
- Zero temporary adapters marked for later cleanup.
- Updated architecture docs merged.
- Program sign-off checklist complete.

## 7) Program Backlog Shape (for Parallel Execution)

- Epic `CR-0`: Complexity Reduction Program (umbrella)
- Epic `CR-A`: Rendering + Formatting decomposition
- Epic `CR-B`: App control-plane decomposition
- Epic `CR-C`: Proxy/CLI simplification
- Epic `CR-D`: AI workbench/analytics decomposition
- For each epic: create 4-8 leaf tasks, each 1-2 days max, independently reviewable.

`// [LAW:no-mode-explosion]` Leaf tasks must remove branches/modes or isolate them at entrypoints; no new deep toggles.

## 8) Verification Protocol (Machine-Verifiable)

Run on every stream PR and at every milestone checkpoint:

```bash
# Full regression gate (CI-enforced)
uv run pytest

# Complexity + LOC snapshots
uv run --with radon radon cc -s -a src/cc_dump
uv run --with radon radon cc -s src/cc_dump > /tmp/radon-cc.txt
find src/cc_dump -name '*.py' -print0 | xargs -0 wc -l | sort -nr > /tmp/loc.txt
```

Required checks:
- Tests: all pass.
- Complexity: target deltas trend down; no new CC > 20 introduced in touched modules.
- LOC: target modules trending downward per stream goals.

`// [LAW:verifiable-goals]` Completion is defined by passing these checks and meeting Section 4 targets.

## 9) Definition of Program Done

Program is complete only when all are true:

1. Stream A/B/C/D target outcomes are met (or documented waivers approved).
2. Top hotspot functions are reduced to agreed thresholds.
3. Full test suite passes in CI on latest `master`.
4. Architecture docs reflect new seams and ownership boundaries.
5. No temporary refactor shims remain.

Until then, this remains top priority work.
