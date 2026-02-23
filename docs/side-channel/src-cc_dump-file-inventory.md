# src/cc_dump File Inventory

Grouped by purpose category (bucket) with fixed-width columns.

## Runtime/Core

```text
FILE                                      BUCKET           LAST_MODIFIED        PURPOSE
----------------------------------------  ---------------  -------------------  -------
__main__.py                               Runtime/Core     2026-01-27 04:36:55  Allow running as `python -m cc_dump`.
cli.py                                    Runtime/Core     2026-02-23 15:54:22  CLI entry point for cc-dump.
pipeline/__init__.py                      Runtime/Core     2026-02-23 15:55:59  Pipeline package.
pipeline/event_types.py                   Runtime/Core     2026-02-21 13:14:37  Type-safe event system for the cc-dump pipeline.
pipeline/har_recorder.py                  Runtime/Core     2026-02-23 15:54:22  HAR recording subscriber for HTTP Archive format output.
pipeline/har_replayer.py                  Runtime/Core     2026-02-23 15:54:22  HAR replay module - loads HAR files and converts to pipeline events.
pipeline/proxy.py                         Runtime/Core     2026-02-23 15:54:22  HTTP proxy handler — pure data source, no display logic.
pipeline/response_assembler.py            Runtime/Core     2026-02-23 15:54:22  Proxy-boundary SSE response assembler.
pipeline/router.py                        Runtime/Core     2026-02-23 15:54:22  Event router for fan-out distribution of proxy events.
pipeline/sentinel.py                      Runtime/Core     2026-02-23 15:54:22  Sentinel interceptor — detects $$ prefix in user messages, short-circuits response.
serve.py                                  Runtime/Core     2026-02-20 23:39:59  Web server entry point using textual-serve.
```

## Core

```text
FILE                                      BUCKET           LAST_MODIFIED        PURPOSE
----------------------------------------  ---------------  -------------------  -------
core/__init__.py                          Core             2026-02-23 15:55:51  Core package.
core/analysis.py                          Core             2026-02-23 01:54:31  Context analytics — token estimation, turn budgets, and tool correlation.
core/formatting.py                        Core             2026-02-23 15:54:22  Request and response formatting — structured intermediate representation.
core/palette.py                           Core             2026-02-20 23:39:59  Color palette generator using golden-angle spacing in HSL space.
core/segmentation.py                      Core             2026-02-20 23:39:59  Segment raw text content into typed SubBlocks for rendering.
core/special_content.py                   Core             2026-02-21 21:52:02  Special request-content classification and navigation markers.
core/token_counter.py                     Core             2026-02-20 23:39:59  Token counting using tiktoken local tokenizer.
```

## TUI

```text
FILE                                      BUCKET           LAST_MODIFIED        PURPOSE
----------------------------------------  ---------------  -------------------  -------
tui/__init__.py                           TUI              2026-01-27 04:36:55  TUI package for cc-dump — Textual-based terminal user interface.
tui/action_config.py                      TUI              2026-02-23 15:54:23  Pure data constants for action handlers — hot-reloadable.
tui/action_handlers.py                    TUI              2026-02-23 15:54:23  Action handlers for navigation, visibility, and panel toggles.
tui/app.py                                TUI              2026-02-23 15:54:23  Main TUI application using Textual.
tui/category_config.py                    TUI              2026-02-23 15:54:23  Category visibility configuration.
tui/chip.py                               TUI              2026-02-21 01:12:20  Reusable chip widgets — lightweight clickable text controls.
tui/custom_footer.py                      TUI              2026-02-23 15:54:23  Custom Footer widget with composed Textual widgets.
tui/dump_export.py                        TUI              2026-02-21 00:03:55  Conversation dump/export to text file.
tui/dump_formatting.py                    TUI              2026-02-23 15:54:23  Block-to-text rendering for conversation dumps.
tui/error_indicator.py                    TUI              2026-02-20 23:39:59  Error indicator overlay for ConversationView.
tui/event_handlers.py                     TUI              2026-02-23 15:54:23  Event handling logic - pure functions for processing proxy events.
tui/hot_reload_controller.py              TUI              2026-02-23 15:54:23  Hot-reload controller — widget replacement and module reload coordination.
tui/info_panel.py                         TUI              2026-02-23 15:54:23  Info panel showing server configuration and connection details.
tui/input_modes.py                        TUI              2026-02-21 21:57:06  Pure mode system for key dispatch.
tui/keys_panel.py                         TUI              2026-02-20 23:39:59  Keys panel showing keyboard shortcuts.
tui/launch_config_panel.py                TUI              2026-02-23 15:54:23  Launch config panel — docked side panel for managing run configurations.
tui/location_navigation.py                TUI              2026-02-21 21:51:41  Shared location navigation helpers for conversation turns.
tui/panel_registry.py                     TUI              2026-02-21 21:26:43  Panel registry — single source of truth for cycling panel configuration.
tui/panel_renderers.py                    TUI              2026-02-23 15:54:23  Panel rendering logic - pure functions for building display text.
tui/protocols.py                          TUI              2026-02-21 22:44:21  Protocol definitions for hot-swappable TUI widgets.
tui/rendering.py                          TUI              2026-02-23 15:54:23  Rich rendering for FormattedBlock structures in the TUI.
tui/search.py                             TUI              2026-02-23 15:54:23  Full-text search for conversation content — vim-style / search.
tui/search_controller.py                  TUI              2026-02-23 15:54:23  Search controller — all search interaction logic.
tui/session_panel.py                      TUI              2026-02-20 23:39:59  Session panel — shows Claude Code connection status.
tui/settings_panel.py                     TUI              2026-02-23 15:54:23  Settings panel — docked side panel for editing app settings.
tui/side_channel_panel.py                 TUI              2026-02-23 15:54:23  Side-channel panel — test UI for AI-powered summaries.
tui/stream_registry.py                    TUI              2026-02-23 15:54:23  Request-scoped stream identity and lane attribution.
tui/styles.css                            TUI              2026-02-21 21:28:27  Textual stylesheet for TUI visual presentation.
tui/theme_controller.py                   TUI              2026-02-21 00:03:59  Theme management for the TUI app.
tui/view_overrides.py                     TUI              2026-02-23 15:54:23  View override store — separates mutable TUI state from immutable domain blocks.
tui/view_store_bridge.py                  TUI              2026-02-21 03:19:06  View store → widget bridge. Builds push callbacks for setup_reactions(). RELOADABLE.
tui/widget_factory.py                     TUI              2026-02-23 15:54:23  Widget factory - creates widget instances that can be hot-swapped.
```

## AI/Side-Channel

```text
FILE                                      BUCKET           LAST_MODIFIED        PURPOSE
----------------------------------------  ---------------  -------------------  -------
ai/__init__.py                            AI/Side-Channel  2026-02-23 15:55:59  AI package.
ai/action_items.py                        AI/Side-Channel  2026-02-22 05:34:19  Action/deferred extraction schema and review-state store.
ai/action_items_beads.py                  AI/Side-Channel  2026-02-23 15:54:23  Optional beads issue bridge for accepted action items.
ai/checkpoints.py                         AI/Side-Channel  2026-02-22 05:29:31  Checkpoint artifacts and deterministic diff rendering.
ai/conversation_qa.py                     AI/Side-Channel  2026-02-22 05:43:48  Scoped conversation Q&A contracts, parsing, and budget estimates.
ai/data_dispatcher.py                     AI/Side-Channel  2026-02-23 15:54:23  Data dispatcher — routes enrichment requests to AI or fallback.
ai/decision_ledger.py                     AI/Side-Channel  2026-02-22 05:26:24  Decision ledger schema and merge semantics.
ai/handoff_notes.py                       AI/Side-Channel  2026-02-22 05:38:18  Structured handoff note artifacts and persistence for resume flows.
ai/incident_timeline.py                   AI/Side-Channel  2026-02-22 05:41:00  Incident/debug timeline artifacts and rendering.
ai/prompt_registry.py                     AI/Side-Channel  2026-02-23 15:54:23  Prompt registry for side-channel purposes.
ai/release_notes.py                       AI/Side-Channel  2026-02-22 06:02:03  Release-note/changelog artifacts, templates, and rendering.
ai/side_channel.py                        AI/Side-Channel  2026-02-23 15:54:23  Side-channel manager — spawns `claude -p` for AI-powered enrichment.
ai/side_channel_analytics.py              AI/Side-Channel  2026-02-22 04:01:46  Side-channel purpose-level analytics.
ai/side_channel_boundary.py               AI/Side-Channel  2026-02-23 15:54:23  Centralized side-channel context boundary (minimization + redaction).
ai/side_channel_marker.py                 AI/Side-Channel  2026-02-23 15:54:23  Side-channel request marker helpers.
ai/side_channel_purpose.py                AI/Side-Channel  2026-02-22 04:58:42  Canonical side-channel purpose taxonomy.
ai/summary_cache.py                       AI/Side-Channel  2026-02-22 05:14:42  Local side-channel summary cache.
ai/utility_catalog.py                     AI/Side-Channel  2026-02-22 06:05:15  Registered lightweight AI utility catalog with lifecycle policy metadata.
```

## Support

```text
FILE                                      BUCKET           LAST_MODIFIED        PURPOSE
----------------------------------------  ---------------  -------------------  -------
__init__.py                               Support          2026-01-27 04:36:55  cc-dump - A transparent proxy for watching Claude Code API traffic.
app/__init__.py                           Support          2026-02-23 15:55:59  App package.
app/analytics_store.py                    Support          2026-02-23 15:54:23  In-memory analytics store for API conversation data.
app/domain_store.py                       Support          2026-02-23 15:54:23  Domain store — append-only domain data for FormattedBlock trees.
app/hot_reload.py                         Support          2026-02-23 15:55:14  Hot-reload watcher for non-proxy modules.
app/launch_config.py                      Support          2026-02-23 15:54:23  Launch configuration model for Claude tmux integration.
app/memory_stats.py                       Support          2026-02-21 23:21:47  Lightweight in-process memory snapshot helpers.
app/settings_store.py                     Support          2026-02-23 15:54:23  Settings store schema and reactions. RELOADABLE.
app/tmux_controller.py                    Support          2026-02-23 15:54:23  Tmux integration for cc-dump — split panes, auto-zoom on API activity.
app/view_store.py                         Support          2026-02-23 15:54:23  View store — category visibility + panel/follow + footer/error/side-channel state. RELOADABLE.
io/__init__.py                            Support          2026-02-23 15:55:59  I/O package.
io/session_sidecar.py                     Support          2026-02-21 22:07:34  UI state sidecar I/O for HAR recordings.
io/sessions.py                            Support          2026-02-21 22:33:05  Session management for HAR recordings.
io/settings.py                            Support          2026-02-23 15:54:23  Settings file I/O for cc-dump.
io/stderr_tee.py                          Support          2026-02-20 23:39:59  Tee stderr to both the real terminal and the TUI LogsPanel.
```

## Eval/Harness

```text
FILE                                      BUCKET           LAST_MODIFIED        PURPOSE
----------------------------------------  ---------------  -------------------  -------
experiments/__init__.py                   Eval/Harness     2026-02-23 15:55:59  Experiments package.
experiments/memory_soak.py                Eval/Harness     2026-02-23 15:54:23  Deterministic memory soak harness for regression checks.
experiments/perf_metrics.py               Eval/Harness     2026-02-23 15:54:23  Lightweight streaming-latency instrumentation for the cc-dump pipeline.
experiments/side_channel_eval.py          Eval/Harness     2026-02-23 15:54:23  Deterministic side-channel evaluation harness.
experiments/side_channel_eval_metrics.py  Eval/Harness     2026-02-22 05:46:31  Canonical machine-verifiable acceptance thresholds for side-channel purposes.
experiments/subagent_enrichment.py        Eval/Harness     2026-02-23 15:54:23  Offline subagent parent-log enrichment for historical analysis.
```

