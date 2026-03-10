# Complexity Audit: cc-dump — Subsystems

**Date:** 2026-03-10  
**Scope:** 8 subsystems across 96 source files in `src/cc_dump` (30,232 LOC)

## Executive Summary
- Total files audited: 96
- Total lines of code: 30,232
- God modules (>500 LOC and/or multi-concern):
  - `src/cc_dump/tui/rendering_impl.py` (4,098)
  - `src/cc_dump/tui/widget_factory.py` (2,610)
  - `src/cc_dump/tui/app.py` (1,566)
  - `src/cc_dump/core/formatting_impl.py` (1,577)
  - `src/cc_dump/pipeline/proxy.py` (757)
  - `src/cc_dump/cli.py` (703)
  - `src/cc_dump/app/analytics_store.py` (740)
  - `src/cc_dump/tui/launch_config_panel.py` (932)
- Dead/vestigial surfaces found:
  - Search navigation stubs left as TODO no-ops (`search_controller.py`)
  - `resolve_proxy_target()` appears unused (`proxy_flow.py`)
  - Legacy/parallel panel surfaces (`economics`/`timeline`) still threaded through handlers despite registry containing only `session` + `stats`
  - Multiple no-op hot-swap APIs (`get_state`/`restore_state`) on panels
- Quick wins (low behavior risk):
  - Remove stale panel branches and legacy wrappers
  - Consolidate duplicated parsing/state extraction helpers
  - Introduce a canonical event-envelope constructor
  - Replace placeholder token formatter and add contract tests

## Module Complexity Map

| Module | Lines | Complexity | Role |
|--------|-------|-----------|------|
| `src/cc_dump/tui` | 16,774 | **HIGH** | Display/runtime orchestration, rendering, interaction, panels |
| `src/cc_dump/core` | 3,211 | **HIGH** | IR + formatting + token/cost analytics |
| `src/cc_dump/pipeline` | 2,734 | **HIGH** | Proxy transport, SSE handling, replay/recording integration |
| `src/cc_dump/app` | 2,898 | **HIGH** | Stores/controllers/hot-reload integration |
| `src/cc_dump/ai` | 2,111 | **MEDIUM-HIGH** | Side-channel orchestration, prompts, artifacts |
| `src/cc_dump/io` | 735 | **MEDIUM** | Sessions/settings/logging/perf output |
| `src/cc_dump` (top-level modules) | 1,073 | **HIGH** | CLI/provider boot/runtime wiring |
| `src/cc_dump/experiments` | 696 | **MEDIUM** | Diagnostics/load tooling (touches internals) |

## Subsystem Boundary Assessment

### TUI
- **Boundary clarity:** ERODED
- **Interface width:** Very wide (`CcDumpApp` constructor and wide render/controller signatures)
- **Deep imports:** Mostly flat import paths, but hidden runtime coupling exists via package attribute access
- **Bidirectional deps:** Hot-reload layer pulls app helpers (`hot_reload_controller` ↔ `app` behavior coupling)
- **Boundary erosion cause:** Legacy panel pathways + private-field reach-ins + monolithic render/widget modules

### Core
- **Boundary clarity:** DIFFUSE
- **Interface width:** `formatting_impl` acts as both IR schema owner and provider adapter
- **Deep imports:** Limited deep imports, but semantic coupling is broad (pipeline/provider assumptions)
- **Bidirectional deps:** No hard cycle detected; conceptual coupling with AI/TUI formatting concerns
- **Boundary erosion cause:** `formatting_impl` combines protocol adaptation, parsing, and UX heuristics

### AI
- **Boundary clarity:** DIFFUSE
- **Interface width:** `DataDispatcher` centralizes many unrelated concerns
- **Deep imports:** Limited structural depth; behavior coupling to core token/model logic and side-channel policy
- **Bidirectional deps:** No direct cycle, but significant two-way conceptual dependency with core semantics
- **Boundary erosion cause:** Dispatcher owns orchestration + fallback rendering + analytics + persistence

### Pipeline/IO
- **Boundary clarity:** DIFFUSE
- **Interface width:** `proxy.py` is broad transport/orchestration hub
- **Deep imports:** Mostly clean; some cross-boundary imports for side-channel/session concerns
- **Bidirectional deps:** App/pipeline coupling present (sentinel typing against app controller)
- **Boundary erosion cause:** Mode permutations concentrated in proxy handler and duplicated provider/envelope logic

### CLI/App Orchestration
- **Boundary clarity:** ERODED
- **Interface width:** `cli.main` wires most runtime domains directly
- **Deep imports:** Wide top-level import fan-out across nearly all subsystems
- **Bidirectional deps:** Runtime state reaches private app internals (`_store_context`, `_error_log`)
- **Boundary erosion cause:** Single entrypoint owns parsing, runtime composition, launch control, and shutdown behavior

## Per-Subsystem Findings

### TUI Findings

1. **What**: Rendering monolith mixes theme runtime, search highlighting, truncation policy, recursive render, and streaming preview.
   - **Where**: `src/cc_dump/tui/rendering_impl.py:176`, `:1086`, `:3160`, `:3369`, `:3941`
   - **Severity**: High
   - **Type**: god-module
   - **Quick win?**: no
   - **Blocks**: Any rendering or visibility feature work due to very high blast radius.

2. **What**: Widget factory combines virtual renderer internals with panel classes/factories and hot-reload state transfer.
   - **Where**: `src/cc_dump/tui/widget_factory.py:206`, `:991`, `:1275`, `:1492`, `:2256`
   - **Severity**: High
   - **Type**: god-module, diffuse-boundary
   - **Quick win?**: partial (extract panel classes first)
   - **Blocks**: Isolated changes to follow mode, panel behavior, or stream preview.

3. **What**: Search navigation behavior is intentionally stubbed (`navigate_next/prev/to_current`) with TODO markers.
   - **Where**: `src/cc_dump/tui/search_controller.py:389`, `:392`, `:403`, `:414`
   - **Severity**: High
   - **Type**: incomplete-refactoring, ux-special-case
   - **Quick win?**: yes
   - **Blocks**: Robust search UX improvements and reliable keyboard navigation.

4. **What**: Legacy panel paths (`economics`/`timeline`) are still wired in actions/hot-reload/app helpers while panel registry only defines `session` and `stats`.
   - **Where**: `src/cc_dump/tui/panel_registry.py:22`, `src/cc_dump/tui/action_handlers.py:527`, `src/cc_dump/tui/app.py:624`, `src/cc_dump/tui/hot_reload_controller.py:609`
   - **Severity**: High
   - **Type**: diffuse-boundary, dead-code
   - **Quick win?**: yes
   - **Blocks**: Clean panel lifecycle and reliable ownership of panel state.

5. **What**: Private-field reach-ins across modules (`conv._turns`, `conv._view_overrides`, internal caches) create hidden coupling.
   - **Where**: `src/cc_dump/tui/location_navigation.py:49`, `src/cc_dump/tui/action_handlers.py:64`, `src/cc_dump/tui/app.py:1502`, `src/cc_dump/tui/widget_factory.py:2241`
   - **Severity**: High
   - **Type**: diffuse-boundary, feature-coupling
   - **Quick win?**: no
   - **Blocks**: Refactoring view/store/widget boundaries without regressions.

6. **What**: Side-channel result state mirrored to two key families (`sc:*` and `workbench:*`).
   - **Where**: `src/cc_dump/tui/side_channel_controller.py:254`, `:259`
   - **Severity**: Medium
   - **Type**: state-duplication
   - **Quick win?**: yes
   - **Blocks**: Single-source state transitions and predictable side-channel UI updates.

### Core + AI Findings

1. **What**: `formatting_impl.py` is a monolith combining IR type definitions, provider-specific request/response formatting, parsing, and presentation heuristics.
   - **Where**: `src/cc_dump/core/formatting_impl.py:942`, `:1307`, `:1557`
   - **Severity**: Critical
   - **Type**: god-module, diffuse-boundary
   - **Quick win?**: no
   - **Blocks**: New provider support and safe formatting changes.

2. **What**: Token formatting is placeholder-only (`fmt_tokens` always returns `"x"`).
   - **Where**: `src/cc_dump/core/analysis.py:27`
   - **Severity**: High
   - **Type**: incomplete-refactoring, ux-special-case
   - **Quick win?**: yes
   - **Blocks**: Trustworthy token/cost UI and diagnostics.

3. **What**: `DataDispatcher` mixes orchestration, prompt generation, fallback policy, artifact persistence, markdown rendering, and analytics.
   - **Where**: `src/cc_dump/ai/data_dispatcher.py:102`, `:173`, `:239`, `:309`, `:395`
   - **Severity**: High
   - **Type**: god-module, scattered-concern
   - **Quick win?**: partial
   - **Blocks**: Side-channel feature additions and reliable policy changes.

4. **What**: Side-channel usage/accounting path appears underpowered for budget enforcement (rollups are sparse while caps depend on token fields).
   - **Where**: `src/cc_dump/ai/data_dispatcher.py:147`, `src/cc_dump/ai/side_channel_analytics.py:26`, `src/cc_dump/ai/side_channel.py:305`
   - **Severity**: High
   - **Type**: state-duplication, incomplete-refactoring
   - **Quick win?**: yes
   - **Blocks**: Verifiable guardrail behavior and cost predictability.

5. **What**: Similar token-estimation and message-scope logic duplicated across core and AI paths.
   - **Where**: `src/cc_dump/core/analysis.py:16`, `src/cc_dump/ai/conversation_qa.py:201`, `src/cc_dump/ai/conversation_qa.py:83`, `src/cc_dump/ai/data_dispatcher.py:543`
   - **Severity**: Medium
   - **Type**: dual-implementation, state-duplication
   - **Quick win?**: yes
   - **Blocks**: Consistent token/scope behavior across user-facing features.

6. **What**: Marker classification ownership is split (`formatting_impl` vs `special_content`).
   - **Where**: `src/cc_dump/core/formatting_impl.py:43`, `src/cc_dump/core/special_content.py:37`
   - **Severity**: Medium
   - **Type**: scattered-concern
   - **Quick win?**: yes
   - **Blocks**: Reliable special-content rendering and future taxonomy changes.

### Pipeline + IO Findings

1. **What**: `proxy.py` carries too many orthogonal modes (forward/reverse, CONNECT, stream/non-stream, emit/no-emit, family strategy), creating permutation risk.
   - **Where**: `src/cc_dump/pipeline/proxy.py:380`, `:441`, `:498`, `:615`, `:653`
   - **Severity**: High
   - **Type**: no-mode-explosion, god-module
   - **Quick win?**: partial
   - **Blocks**: Adding providers/protocol changes safely.

2. **What**: Event envelope fields (`request_id`, `seq`, `recv_ns`, `provider`) are manually threaded in multiple paths (proxy + replay).
   - **Where**: `src/cc_dump/pipeline/proxy.py:420`, `:524`, `:551`, `:630`, `src/cc_dump/pipeline/har_replayer.py:186`
   - **Severity**: High
   - **Type**: parameter-threading, state-duplication
   - **Quick win?**: yes
   - **Blocks**: Deterministic event semantics across live/replay/recording.

3. **What**: Unknown provider families silently fall back to OpenAI extraction/assembly.
   - **Where**: `src/cc_dump/pipeline/proxy.py:252`, `:622`
   - **Severity**: Medium
   - **Type**: ux-special-case, incomplete-refactoring
   - **Quick win?**: yes
   - **Blocks**: Safe onboarding of new provider families; failures become harder to detect.

4. **What**: Provider inference logic is duplicated across sessions and replayer.
   - **Where**: `src/cc_dump/io/sessions.py:46`, `:90`, `src/cc_dump/pipeline/har_replayer.py:125`, `:138`
   - **Severity**: Medium
   - **Type**: dual-implementation
   - **Quick win?**: yes
   - **Blocks**: Consistent replay/listing semantics.

5. **What**: `resolve_proxy_target()` appears unused while a more specific resolver is active.
   - **Where**: `src/cc_dump/pipeline/proxy_flow.py:27`
   - **Severity**: Medium
   - **Type**: dead-code, incomplete-refactoring
   - **Quick win?**: yes
   - **Blocks**: Clarity for future proxy-flow changes.

### CLI + App-Orchestration Findings

1. **What**: `cli.main` is a broad multi-domain orchestrator (arg parse, replay, proxy boot, tmux, side-channel, stores, app lifecycle, shutdown).
   - **Where**: `src/cc_dump/cli.py:326`, `:453`, `:512`, `:575`, `:673`
   - **Severity**: High
   - **Type**: god-module, feature-coupling
   - **Quick win?**: partial
   - **Blocks**: Any entrypoint/runtime changes without broad regression risk.

2. **What**: Runtime state has overlapping representations (`state`, `provider_states`, `store_context`) and private app internals are touched directly.
   - **Where**: `src/cc_dump/cli.py:529`, `:650`, `:652`, `:666`, `:672`, `:677`
   - **Severity**: High
   - **Type**: state-duplication, diffuse-boundary
   - **Quick win?**: no
   - **Blocks**: Clear ownership of runtime state and safe app API evolution.

3. **What**: `TmuxController` has dual launch-env paths (`_launch_env` and legacy `_port` fallback), and CLI feeds both.
   - **Where**: `src/cc_dump/app/tmux_controller.py:129`, `:181`, `:419`, `src/cc_dump/cli.py:592`, `:595`
   - **Severity**: High
   - **Type**: state-duplication, incomplete-refactoring
   - **Quick win?**: yes
   - **Blocks**: Provider-agnostic launch behavior and deterministic env wiring.

4. **What**: Dynamic argparse attribute synthesis couples naming conventions to provider keys.
   - **Where**: `src/cc_dump/cli.py:183`, `:191`, `:411`
   - **Severity**: Medium
   - **Type**: parameter-threading
   - **Quick win?**: yes
   - **Blocks**: Extending provider config safely.

5. **What**: Experiments access private internals of production components.
   - **Where**: `src/cc_dump/experiments/memory_soak.py:51`, `:53`, `:127`, `:133`
   - **Severity**: Medium
   - **Type**: diffuse-boundary
   - **Quick win?**: partial
   - **Blocks**: Refactoring production internals without breaking diagnostics tooling.

## Recommended Complexity Reduction Plan

### Phase 1: Quick Wins (remove dead weight)
1. Remove stale panel branches (`economics`/`timeline`) from app/action/hot-reload pathways to align with `panel_registry`.
2. Delete or repurpose unused `resolve_proxy_target()`.
3. Replace `fmt_tokens` placeholder with real formatting and add coverage in panel/dump rendering tests.
4. Deduplicate session-id extraction and side-channel result key mapping.
5. Remove legacy tmux `_port` fallback path and standardize on one launch-env source.

### Phase 2: Consolidate Duplication
1. Introduce canonical event envelope constructor used by proxy + replayer.
2. Centralize provider inference policy used by sessions + replayer.
3. Extract shared AI scope/token helpers used by `conversation_qa` and `data_dispatcher`.
4. Consolidate marker classification into a single core classifier.

### Phase 3: Decompose God Modules
1. Split `tui/rendering_impl.py` by change reason (theme runtime, block renderers, search highlight/gutter, streaming).
2. Split `tui/widget_factory.py` into (a) conversation view engine and (b) panel widgets/factories.
3. Split `core/formatting_impl.py` into provider adapters + IR constructors + special-content classifier integration.
4. Split `pipeline/proxy.py` into transport adapter + event/orchestration layer.
5. Convert `cli.main` into phase pipeline (`parse -> preflight -> runtime boot -> app boot -> shutdown`) with typed runtime context.

### Phase 4: Feature Cuts (evaluate with user)
1. Decide whether legacy panel APIs (`economics`/`timeline`) should be deleted entirely or reintroduced through registry.
2. Decide whether search navigation should be fully restored now or removed from keymap until redesigned.
3. Decide whether experiment tooling should remain allowed to touch internals or move behind explicit diagnostics interfaces.

## Complexity Blockers for Future Work
1. Rendering and widget monoliths in TUI make even small UI changes expensive and regression-prone.
2. Formatting/proxy/CLI concentration creates large blast radius for new provider/protocol features.
3. State duplication across runtime/store/controller layers prevents one authoritative model for session/stream/side-channel behavior.
4. Incomplete refactors (search stubs, placeholder token formatting, legacy wrappers) make behavior difficult to reason about and verify.

## Risk Assessment

| Cut/Simplification | Risk | Mitigation |
|-----|------|------------|
| Remove stale panel branches (`economics`/`timeline`) | Low | Keep registry-driven panel tests; verify command palette panel cycle behavior |
| Delete `resolve_proxy_target()` | Low | Add/keep proxy target resolution tests around `resolve_proxy_target_for_origin()` |
| Remove tmux legacy `_port` fallback | Medium | Add launch profile compatibility test matrix (tmux/no-tmux, provider variants) |
| Split `formatting_impl.py` | High | Characterization tests over provider request/response formatting before extraction |
| Split `rendering_impl.py` | High | Snapshot/golden tests for render strips, search highlights, and visibility modes |
| Split `proxy.py` | High | End-to-end replay/live parity tests and event sequencing assertions |

## Notes on Method
- This audit used subsystem mode (large-project path): `src/cc_dump` was evaluated end-to-end with parallel subsystem reviews plus quantitative metrics (LOC, branch density, import fan-out).
- Only architectural complexity findings were included; style, security, and performance-only concerns were excluded.
