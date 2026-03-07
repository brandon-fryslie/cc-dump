# Complexity Audit: cc-dump — Features

**Date:** 2026-03-06
**Scope:** 105 features across 93 source files (32,070 LOC)
**Mode:** Feature-oriented — every user-visible feature traced across the codebase

## Executive Summary

- **Features audited:** 105
- **Features rated HIGH complexity:** Rendering/Visibility System (4,362-line rendering_impl.py), AI Workbench (1,524 lines across 14 modules), Launch Config (1,153 lines across 3 modules), Search (1,106 lines across 2 modules)
- **Features that touch 3+ subsystems:** Search (5), AI Workbench (7), Launch/Tmux (5), Filterset Presets (4), Multi-Provider Proxy (7), View Overrides (4 writers)
- **Dead/vestigial code identified:** ~1,200 lines
- **Quick wins (zero-risk removals):** ~400 lines

## Feature-by-Feature Complexity Assessment

---

### 1. Reverse Proxy Mode
**Complexity: LOW | Value: HIGH | Verdict: KEEP**
- **What:** Intercepts Anthropic API traffic as a reverse proxy
- **Where:** `cli.py`, `pipeline/proxy.py`, `providers.py` (~50 lines of feature-specific code)
- **Files touched:** 3
- **State:** `ProxyHandler.target_host` class attribute
- **Coupling:** Clean. `proxy.py` reads `providers.api_paths` for JSON body detection.
- **Boundary erosion:** None.
  VERDICT: CORE

### 2. Forward Proxy Mode (HTTP CONNECT)
**Complexity: MODERATE | Value: MODERATE | Verdict: KEEP**
- **What:** HTTP CONNECT forward proxy with TLS interception for non-Anthropic providers
- **Where:** `pipeline/proxy.py` (55 lines), `pipeline/forward_proxy_tls.py` (175 lines), `cli.py`
- **Files touched:** 4
- **State:** `ForwardProxyCertificateAuthority._host_contexts` (thread-safe cert cache), `_tmp_dir` (temp certs)
- **Coupling:** `do_CONNECT()` mutates `self.provider` by calling back into providers registry — a single handler instance serves two providers' state during a tunnel lifetime.
- **Boundary erosion:** `launcher_registry.py` reaches into `provider_endpoints["forward_proxy_ca_cert_path"]` — conditionally-present key couples launcher to TLS feature.
VERDICT: CORE

### 3. HAR Recording
**Complexity: MODERATE | Value: HIGH | Verdict: KEEP**
- **What:** Records all proxied API traffic to HAR 1.2 format files
- **Where:** `pipeline/har_recorder.py` (393 lines)
- **Files touched:** 5
- **State:** `_pending_by_request` OrderedDict (bounded at 256), lazy file handle, byte offset for incremental writes
- **Special-case logic:** 6 branches
- **Coupling:** `har_recorder.py` imports `cc_dump.ai.side_channel_marker.extract_marker` — the recording subsystem reaches into the AI enrichment subsystem to label entries.
- **Boundary erosion:** YES — pipeline (HAR recording) has compile-time dependency on AI (side channel). This is the most notable cross-domain coupling in the proxy layer.
VERDICT: CORE


### 4. HAR Replay
**Complexity: LOW | Value: HIGH | Verdict: KEEP**
- **What:** Loads HAR files and synthesizes events through the pipeline
- **Where:** `pipeline/har_replayer.py` (199 lines)
- **Files touched:** 5
- **State:** `app._replay_data` (in-memory list), `_replay_complete` threading.Event
- **Coupling:** `_drain_events()` in app.py blocks on `_replay_complete.wait()` — live event draining is coupled to replay feature through a threading event.
VERDICT: CORE

### 6. 3-Level Visibility System
**Complexity: MODERATE | Value: HIGH | Verdict: KEEP**
- **What:** EXISTENCE/SUMMARY/FULL per category with per-block overrides
- **Where:** `category_config.py` (21 lines), `view_store.py` (230 lines), `rendering_impl.py`, `view_overrides.py` (144 lines)
- **Files touched:** 8
- **State:** 18 store keys (6 categories × 3 axes: vis/full/exp), `ViewOverrides._blocks` dict
- **Why it works:** Data-driven design with `CATEGORY_CONFIG`, `VIS_CYCLE`, `VIS_TOGGLE_SPECS`, `TRUNCATION_LIMITS` tables. `_resolve_visibility()` is the single enforcer.
VERDICT: CORE

### 7. Click-to-Expand/Collapse
**Complexity: MODERATE | Value: HIGH | Verdict: KEEP**
- **What:** Clicking blocks toggles their individual expansion state
- **Where:** `widget_factory.py` (click handler), `rendering_impl.py` (meta segments), `view_overrides.py`
- **Files touched:** 3
- **Boundary erosion:** `RegionViewState.strip_range` is renderer-internal data stored in a "view state" struct — the renderer writes rendering artifacts into shared state that the click handler reads. This is a clear mixed-responsibility in `ViewOverrides`.
VERDICT: BROKEN

### 8. Rendering Pipeline (Markdown, Code Highlighting, XML Collapsible)
**Complexity: HIGH | Value: HIGH | Verdict: KEEP (but note size)**
- **What:** Two-stage pipeline: FormattedBlock IR → Rich Text strips
- **Where:** `rendering_impl.py` (4,362 lines), `formatting_impl.py` (1,694 lines)
- **Files touched:** 6
- **Why it's complex:** The rendering file is the largest in the codebase. However, complexity is well-managed: dispatch tables replace if/else chains, renderers are per-block-type functions.
- **Boundary erosion:** `rendering_impl.py` calls `populate_content_regions()` from `formatting_impl.py` during rendering — lazy evaluation blurs the two-stage pipeline boundary. `rendering_impl.py` also writes `expandable` and `strip_range` back to `ViewOverrides` as side effects of rendering.
- **If removed:** N/A — this is the core rendering engine. Size could be reduced by extracting renderer functions into separate modules by block type.
  VERDICT: CORE, but need refactor to solve boundary erosion

### 10. Tool Use Correlation and Summaries
**Complexity: LOW | Value: HIGH | Verdict: KEEP**
- **What:** At SUMMARY level, consecutive tool use/result pairs collapse into ToolUseSummaryBlock
- **Where:** `rendering_impl.py` (`_collapse_children()`)
- **Coupling:** `force_vis` in `BlockViewState` can prevent collapse — search feature overrides tool correlation.
VERDICT: resolve

### 13. Search System
**Complexity: HIGH | Value: HIGH | Verdict: KEEP (but decouple)**
- **What:** Vim-style / search with 4 modes, incremental matching, auto-expand, position restore
- **Where:** `search.py` (573 lines), `search_controller.py` (533 lines) = 1,106 lines total
- **Files touched:** 7
- **State:** `SearchState` wraps 6 store keys + transient state (matches, saved_filters, expanded_blocks, debounce_timer, saved_scroll_y, text_cache)
- **Special-case logic:** ~20+ branches in search_controller
- **Why it's complex:** `search_controller.py` is the most heavily coupled module — it reaches into `ConversationView._turns` (private), `_view_overrides`, `_scroll_anchor`, `scroll_offset`, and calls `rerender()`, `mark_overrides_changed()`, `ensure_turn_rendered()`. 6+ private ConversationView members accessed directly.
- **Boundary erosion:** `search_controller` directly manipulates `ViewOverrides._search_block_ids` and sets `BlockViewState.force_vis`. The controller is not a widget but accesses widget-internal objects.
- **If simplified:** Extract a `ConversationNavigator` interface that exposes the needed operations without exposing private fields.
  VERDICT: CORE, but needs refactor

### 14. Follow Mode
**Complexity: MODERATE | Value: HIGH | Verdict: KEEP**
- **What:** Auto-scroll with 3 states (ACTIVE/ENGAGED/OFF) driven by lookup tables
- **Where:** `widget_factory.py` (4 state transition tables), `action_handlers.py`, `custom_footer.py`
- **Coupling:** `action_handlers.go_top` imports `_FOLLOW_DEACTIVATE` (private table) from `widget_factory` — crosses into the follow-state machine's internals from navigation.
VERDICT: CORE, but needs refactor

### 15. AI Workbench Panel
**Complexity: HIGH | Value: MODERATE | Verdict: EVALUATE**
- **What:** Docked panel for AI-powered conversation analysis (summarize, Q&A, action items, utilities)
- **Where:** `ai/` directory (14 files, ~2,600 lines), `tui/side_channel_panel.py` (606 lines), `tui/side_channel_controller.py` (918 lines) = ~4,100 lines total
- **Files touched:** 14+ across ai/, tui/, app/
- **State:** 6 `sc:*` view store keys, `app._sc_action_batch_id`, `app._sc_action_items`, `SideChannelAnalytics`, `SummaryCache`, `ActionItemStore`, `HandoffStore`
- **Why it's complex:** `side_channel_controller.py` (918 lines) accepts `app` as omniscient parameter and reads from 10+ distinct app attributes. Two parallel usage tracking systems exist (`SideChannelAnalytics` in data_dispatcher vs `AnalyticsStore.get_side_channel_purpose_summary()`). Panel open resets action-item state (feature bleeding).
- **Coupling:** Every controller function accepts `app` and reaches into `app._view_store`, `app._data_dispatcher`, `app._analytics_store`, `app._app_state`, `app._sc_action_batch_id`, etc. Capabilities-over-context violation.
- **Boundary erosion:** Workbench results view receives data via two different mechanisms: sidebar preview through reactive store, full-width markdown through direct widget call. Two update paths for the same data.
VERDICT: CUT TO MINIMUM: Handoff, Q&A, light utility features.  Enforce strict boundary

### 16. Handoff Note Draft
**Complexity: MODERATE | Value: LOW | Verdict: CONSIDER REMOVING**
- **What:** Generates structured handoff notes from conversation
- **Where:** `ai/handoff_notes.py` (267 lines), `ai/data_dispatcher.py` (~78 lines)
- **Dead code:** ~350 lines total. The UI control has `availability="placeholder"` and dispatches to `workbench_preview()` (a stub) instead of the real implementation. `generate_handoff_note`, `HandoffStore`, `HandoffArtifact`, `parse_handoff_artifact`, `render_handoff_markdown`, `latest_handoff_note`, `handoff_note_snapshot` — all unreachable from the TUI.
- **If removed:** Delete `ai/handoff_notes.py` entirely, remove handoff methods from `data_dispatcher.py`. ~350 lines removed with zero behavioral change.

### 17. Side Channel Analytics (Dual Tracking)
**Complexity: LOW | Value: LOW | Verdict: SIMPLIFY**
- **What:** Token usage tracking for side-channel operations, segmented by purpose
- **Where:** `ai/side_channel_analytics.py` (56 lines), `ai/data_dispatcher.py`, `app/analytics_store.py`
- **Dead code:** `SideChannelAnalytics` in `data_dispatcher.py` is structurally wired but all token fields remain 0 because callers never pass them. `DataDispatcher.side_channel_usage_snapshot()` is defined but never called from the TUI. The TUI uses `AnalyticsStore.get_side_channel_purpose_summary()` instead.
- **If simplified:** Remove `SideChannelAnalytics` class and `side_channel_usage_snapshot()` method. ~60 lines removed. One source of truth (AnalyticsStore) remains.
VERDICT: Important to track sidechannel costs.  But this should happen from standard analytics, not the other way around

### 18. Summary Cache
**Complexity: LOW | Value: LOW | Verdict: EVALUATE**
- **What:** Avoids duplicate AI calls for identical message sets
- **Where:** `ai/summary_cache.py` (135 lines)
- **Coupling:** Only `summarize_messages` uses the cache. Q&A, action extraction, utilities, and checkpoints do NOT check the cache. Narrow scope limits value.
- **If generalized:** Extend cache to all side-channel operations, or remove if hit rate is negligible.
VERDICT: KILL

### 19. CycleSelector / MultiCycleSelector Widgets
**Complexity: MODERATE | Value: LOW | Verdict: EVALUATE**
- **What:** Inline cycle/multi-select widgets
- **Where:** `tui/cycle_selector.py` (529 lines)
- **Coupling:** `CycleSelector` is used only in `LaunchConfigPanel` (config selector + launcher selector). `MultiCycleSelector` appears unused. The Q&A scope selector uses Textual's built-in `Select` widget instead, despite CycleSelector being documented as the intended widget.
- **If removed/consolidated:** If MultiCycleSelector has no consumers, remove it (~200 lines). If CycleSelector's only consumer is launch_config_panel, consider whether a standard Select would suffice.
  VERDICT: KILL

### 20. Launch Configuration System
**Complexity: HIGH | Value: MODERATE | Verdict: SIMPLIFY**
- **What:** Create and manage named run configs for spawning coding tools
- **Where:** `app/launch_config.py` (452 lines), `tui/launch_config_panel.py` (701 lines), `tui/settings_launch_controller.py` (123 lines) = 1,276 lines
- **Files touched:** 6
- **State:** Three representations of "active config": on-disk (`settings.json["active_launch_config"]`), runtime view store (`launch:active_name`), and in-panel transient (`LaunchConfigPanel._active_name`). These can diverge.
- **Special-case logic:** ~20+ branches for form field editing, add/remove/rename, shell-display conversion
- **Coupling:** `settings_launch_controller.launch_with_config()` reaches into `app._tmux_controller`, `app._provider_endpoints`, `app._active_resume_session_id()`, and the view store simultaneously.
- **If simplified:** The panel at 701 lines is the largest single panel. Consider whether all options are actually used or if a simpler config format would suffice.

### 21. Tmux Integration
**Complexity: MODERATE | Value: HIGH | Verdict: KEEP**
- **What:** Launch tool in tmux split, pane adoption, zoom, auto-zoom, log tail
- **Where:** `app/tmux_controller.py` (611 lines)
- **State:** `_tool_pane`, `state` enum, `pane_alive` Observable, `_is_zoomed`, `auto_zoom_state`
- **Coupling:** Auto-zoom decisions driven by `_ZOOM_DECISIONS` table (data-driven, clean). Two paths to sync tmux state: reactive reaction in lifecycle_controller AND direct `_sync_tmux_to_store()` calls from action handlers.

### 22. Theme Cycling
**Complexity: LOW | Value: MODERATE | Verdict: KEEP**
- **What:** Cycles through Textual themes with [ / ] keys
- **Where:** `tui/theme_controller.py` (56 lines)
- **Coupling:** `apply_markdown_theme()` calls into `rendering.get_runtime_from_owner()` and `get_theme_colors()`.

### 23. Color Palette Seed Hue
**Complexity: LOW | Value: LOW | Verdict: KEEP (fix bug)**
- **What:** `--seed-hue` / `CC_DUMP_SEED_HUE` for terminal color palette
- **Where:** `core/palette.py` (482 lines)
- **Bug:** `init_palette()` is called once at startup but not re-called on hot-reload. After hot-reload, the palette re-initializes from the env var, silently dropping the `--seed-hue` CLI value.

### 24. Hot Reload
**Complexity: HIGH | Value: HIGH | Verdict: KEEP (architectural necessity)**
- **What:** Auto-reload rendering pipeline on file change, reconstruct all widgets
- **Where:** `app/hot_reload.py` (235 lines), `tui/hot_reload_controller.py` (631 lines) = 866 lines
- **Files touched:** 10+ (must touch almost everything to reconstruct state)
- **Coupling:** `_do_hot_reload()` calls into rendering, theme controller, settings store, view store, view store bridge, search controller. This is the highest-coupling module in the system — architecturally necessary.
- **Dead code:** `_legacy_default_conversation_swap()` — back-compat path for single-conversation apps; never fires in current code.

### 25. Session Sidecar
**Complexity: LOW | Value: MODERATE | Verdict: KEEP (fix duplication)**
- **What:** Serializes UI state alongside HAR file as `.ui.json`
- **Where:** `io/session_sidecar.py` (58 lines)
- **One-source-of-truth violation:** `.ui.json` suffix is known in three places: `session_sidecar.sidecar_path_for_har()`, `cli.py` (indirectly), and `sessions.cleanup_recordings()` (hardcoded at line 222). Cleanup should call `sidecar_path_for_har()`.

### 26. Conversation Dump
**Complexity: LOW | Value: MODERATE | Verdict: KEEP**
- **What:** Export visible conversation to text file
- **Where:** `tui/dump_export.py` (100 lines), `tui/dump_formatting.py` (244 lines)
- **Special case:** macOS-only auto-open in `$VISUAL`. No extension point for other platforms.

### 27. Settings Persistence
**Complexity: MODERATE | Value: HIGH | Verdict: SIMPLIFY**
- **What:** Persists theme, auto-zoom, AI toggle, launch configs to settings.json
- **Where:** `io/settings.py` (120 lines), `app/settings_store.py` (184 lines)
- **Two persistence paths:** SCHEMA-keyed settings go through settings_store → reaction → io/settings. Launch configs bypass the store entirely and call io/settings directly. Not unified.
- **Dead code:** `"filtersets"` read path in `get_filterset()` — reads saved data, logs warning, ignores it.

### 28. Panel System
**Complexity: LOW | Value: HIGH | Verdict: KEEP**
- **What:** Cycling right sidebar (session, stats, no panel)
- **Where:** `tui/panel_registry.py` (30 lines)
- **Boundary erosion:** `refresh_active_panel` has hardcoded `"session"` string check — the one panel with a different refresh path.
- **Dead code:** `ToolEconomicsPanel` (~75 lines) + `create_economics_panel()` + `render_economics_panel()` (~80 lines) — defined but never mounted, not in PANEL_REGISTRY. `TimelinePanel` (~75 lines) + factory — same situation. `StatsPanel.update_stats()` + `request_count`/`models_seen` — retained for "compatibility" but no longer displayed.

### 29. Debug Settings Panel
**Complexity: LOW | Value: LOW | Verdict: KEEP**
- **What:** Runtime debug toggles (log level, perf logging, memory snapshots)
- **Where:** `tui/debug_settings_panel.py` (175 lines)
- **Boundary erosion:** Directly mutates `app._memory_snapshot_enabled` — bypasses store/reaction system.

### 30. `--continue` vs `--resume` Overlap
**Complexity: LOW | Value: LOW | Verdict: CONSOLIDATE**
- **What:** Two CLI flags that do nearly the same thing
- `--continue` mutates `args.replay` to latest recording. `--resume` also sets `args.replay`. Both end up in the same `if args.replay:` block that loads the sidecar.
- **If consolidated:** Make `--continue` an alias for `--resume latest` or document the distinction clearly.

### 31. View Overrides (Cross-Cutting Infrastructure)
**Complexity: HIGH | Value: HIGH | Verdict: KEEP (but note mixed responsibility)**
- **What:** Per-block mutable view state (expansion, search force-vis, expandability)
- **Where:** `tui/view_overrides.py` (144 lines)
- **Written by 4 subsystems:** renderer (expandable, strip_range), search (force_vis), click handler (expanded), keyboard actions (clear_category). Most heavily coupled object in the codebase.
- **Boundary erosion:** `RegionViewState.strip_range` is renderer-internal data (which lines a region occupies) stored in a "view state" struct alongside user-facing state. `BlockViewState.expandable` is similarly renderer output in a view state object. Rendering writes to ViewOverrides as a side effect — rendering is not read-only.

---

## Dead Code & Quick Wins

### Dead/Unused Modules & Functions

| Item | Location | Lines | Action |
|------|----------|-------|--------|
| Handoff note implementation | `ai/handoff_notes.py` (all) + `data_dispatcher.py` methods | ~350 | **REMOVE** — UI has `availability="placeholder"`, code is unreachable |
| `SideChannelAnalytics` class | `ai/side_channel_analytics.py` | ~56 | **REMOVE** — token fields always 0, `side_channel_usage_snapshot()` never called from TUI |
| `ToolEconomicsPanel` + factory + renderer | `widget_factory.py`, `panel_renderers.py` | ~155 | **REMOVE** — never mounted, not in PANEL_REGISTRY |
| `TimelinePanel` + factory | `widget_factory.py` | ~75 | **REMOVE** — never mounted, not in PANEL_REGISTRY |
| `StatsPanel.update_stats()` + `request_count`/`models_seen` | `widget_factory.py` | ~20 | **REMOVE** — "retained for compatibility" but no longer displayed |
| `_legacy_default_conversation_swap()` | `hot_reload_controller.py` | ~15 | **REMOVE** — back-compat path that never fires |
| `update_search_bar()` shim | `search_controller.py` | ~8 | **REMOVE** — "backward-compatible shim during migration" |
| `SessionPanel.refresh_from_store()` no-op stub | `session_panel.py` | ~2 | **REMOVE** |
| `openai_port` / `openai_target` vestigial params | `app.py` | ~15 | **REMOVE** — always overridden by `provider_endpoints` |
| Filterset stale-data check | `settings.py:get_filterset()` | ~5 | **REMOVE** — reads saved data, warns, then ignores |
| `collect_values()` 3-way branch | `settings_panel.py` | ~6 | **SIMPLIFY** — all branches are identical (all return `widget.value`) |

**Total dead code:** ~707 lines removable with zero behavioral change

### Duplicate Data

| Concern | Location A | Location B | Action |
|---------|-----------|-----------|--------|
| Sidecar path suffix `.ui.json` | `session_sidecar.sidecar_path_for_har()` | `sessions.cleanup_recordings()` (hardcoded) | Use `sidecar_path_for_har()` in cleanup |
| Provider detection (multi-tier) | `har_replayer.py` | `sessions.py` | Extract shared function |
| Hardcoded `"anthropic"` string | `cli.py:429,601,618` | `providers.DEFAULT_PROVIDER_KEY` | Use the constant |
| Duplicate `("D", "Debug")` in KEY_GROUPS | `input_modes.py:228` | `input_modes.py:232` | Remove duplicate |
| `UtilityRegistry` double instantiation | `side_channel_panel.py` | `data_dispatcher.py` | Share single instance |

### Feature Overlap

| Feature A | Feature B | Overlap | Action |
|-----------|-----------|---------|--------|
| `--continue` | `--resume latest` | Nearly identical behavior | Consolidate |
| `SideChannelAnalytics` | `AnalyticsStore.get_side_channel_purpose_summary()` | Parallel usage tracking | Remove `SideChannelAnalytics` |

---

## Complexity Blockers for Future Work

### 1. Adding a new AI workbench operation
**What blocks it:** `side_channel_controller.py` (918 lines) accepts `app` as an omniscient parameter. Adding a new operation means adding another function that reaches into 10+ app attributes. The controller has no abstraction layer — it's raw imperative code touching everything.
**Simplify first:** Extract a `WorkbenchContext` that exposes only the needed capabilities (messages, dispatcher, store, analytics) instead of passing the full app object.

### 2. Adding a new content category
**What blocks it:** Very little — the category system is well data-driven. Add an entry to `CATEGORY_CONFIG`, add renderers to `BLOCK_RENDERERS`, done. This is a complexity success story.

### 3. Adding a new panel type
**What blocks it:** `refresh_active_panel` has a hardcoded `"session"` string check for the one panel with a different refresh path. New panels must know whether to use `refresh_from_store()` or a custom path. `ToolEconomicsPanel` and `TimelinePanel` were apparently built but never wired — suggesting the wiring is non-trivial.
**Simplify first:** Unify the panel refresh protocol. All panels should implement the same interface.

### 4. Refactoring ViewOverrides
**What blocks it:** 4 subsystems write to it (renderer, search, click handler, keyboard actions). Any change to ViewOverrides' API requires coordinated changes across rendering, search, and widget code. `strip_range` and `expandable` are renderer artifacts stored alongside user-facing state — extracting them would require a parallel struct.

### 5. Rendering performance optimization
**What blocks it:** `rendering_impl.py` at 4,362 lines is a single module. While internally well-organized with dispatch tables, any change to rendering requires navigating one massive file. The lazy `populate_content_regions()` call from rendering blurs the two-stage pipeline.

---

## Recommended Complexity Reduction Plan

### Phase 1: Quick Wins — Remove Dead Weight (~700 lines, zero risk)

1. Delete `ai/handoff_notes.py` entirely, remove handoff methods from `data_dispatcher.py` (~350 lines)
2. Delete `SideChannelAnalytics` class and `side_channel_usage_snapshot()` method (~60 lines)
3. Delete `ToolEconomicsPanel`, `TimelinePanel`, their factories and renderers from `widget_factory.py` and `panel_renderers.py` (~230 lines)
4. Delete `StatsPanel.update_stats()`, `request_count`, `models_seen` (~20 lines)
5. Delete `_legacy_default_conversation_swap()` from `hot_reload_controller.py` (~15 lines)
6. Delete `update_search_bar()` shim from `search_controller.py` (~8 lines)
7. Delete `openai_port`/`openai_target` vestigial params and fallback code from `app.py` (~15 lines)
8. Remove duplicate `("D", "Debug")` entry from `KEY_GROUPS` in `input_modes.py`
9. Fix `collect_values()` in `settings_panel.py` — collapse 3 identical branches to 1

### Phase 2: Fix Duplications (~50 lines of fixes)

1. Use `sidecar_path_for_har()` in `sessions.cleanup_recordings()` instead of hardcoding `.ui.json`
2. Replace hardcoded `"anthropic"` strings in `cli.py` with `DEFAULT_PROVIDER_KEY`
3. Extract shared provider detection function from `har_replayer.py` and `sessions.py`
4. Fix `--seed-hue` bug: re-apply CLI seed hue after hot-reload

### Phase 3: Simplify High-Complexity Features

1. **AI Workbench controller:** Extract `WorkbenchContext` interface to replace omniscient `app` parameter
2. **ViewOverrides:** Separate renderer artifacts (`strip_range`, `expandable`) from user-facing state (`expanded`, `force_vis`) into parallel structs
3. **Multi-provider dict:** Replace untyped `provider_endpoints` dict with `ProviderEndpoint` dataclass
4. **Settings persistence:** Unify the two persistence paths (settings_store reactions vs direct io/settings calls)
5. **Panel refresh:** Unify the panel refresh protocol — remove `"session"` special case

### Phase 4: Feature Cuts (Evaluate with User)

1. **Handoff notes** — already dead code, just needs cleanup (Phase 1)
2. **MultiCycleSelector** — appears unused, ~200 lines
3. **Summary cache scope** — either generalize to all AI operations or evaluate if hit rate justifies 135 lines
4. **`--continue` flag** — consolidate with `--resume latest`

---

## Risk Assessment

| Cut | Risk | Mitigation |
|-----|------|------------|
| Delete handoff_notes.py | **Zero** | Code is unreachable — UI dispatches to placeholder |
| Delete SideChannelAnalytics | **Zero** | TUI uses AnalyticsStore instead, never calls snapshot() |
| Delete ToolEconomicsPanel/TimelinePanel | **Zero** | Never mounted, not in PANEL_REGISTRY |
| Delete StatsPanel.update_stats() | **Low** | May break tests that call it — check test files first |
| Delete openai_port/openai_target | **Zero** | Always overridden by provider_endpoints |
| Fix hardcoded "anthropic" strings | **Zero** | Pure constant replacement |
| Fix sidecar path duplication | **Zero** | Pure refactor — same output |
| Consolidate --continue/--resume | **Low** | Check if any scripts/docs depend on --continue specifically |
| Extract WorkbenchContext | **Low** | Internal refactor, no behavior change |
| Replace provider_endpoints dict with dataclass | **Low** | Internal refactor, improves type safety |
