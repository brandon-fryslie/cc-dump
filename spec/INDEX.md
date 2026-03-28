# cc-dump Specification Index

> Generated: 2026-03-28 (Iteration 1, reviewed and corrected)

## Status Tracker

| File | Status | Summary |
|------|--------|---------|
| [events.md](events.md) | reviewed | Event types, fields, ordering guarantees, lifecycle of an API call. Dead code identified (ResponseSSEEvent, ResponseNonStreamingEvent). |
| [formatting.md](formatting.md) | reviewed | FormattedBlock IR: 26 block types, system prompt tracking, tool correlation, text segmentation. Content region motivation added. |
| [visibility.md](visibility.md) | reviewed | 3-axis visibility system: 6 categories, VisState booleans, keyboard cycling, filtersets (hardcoded, not configurable). |
| [rendering.md](rendering.md) | reviewed | Block rendering at each visibility state, truncation limits, two-tier dispatch, gutter system. 6 missing block types added. |
| [navigation.md](navigation.md) | reviewed | Keyboard shortcuts, vim navigation, input modes, follow mode. F1-F9 confirmed unimplemented. Click-to-expand confirmed unimplemented. |
| [cli.md](cli.md) | reviewed | CLI flags, subcommands, environment variables, startup sequence (reordered for accuracy), exit codes. |
| [recording.md](recording.md) | reviewed | HAR recording/replay format, storage paths, CLI flags, live vs replay divergences. Replay blocking overclaim removed. |
| [proxy.md](proxy.md) | reviewed | HTTP proxy: reverse/forward modes, TLS, port assignment, provider routing, event emission. ProviderSpec fields completed. |
| [analytics.md](analytics.md) | reviewed | Token/cost tracking, TurnRecord model, dashboard views (sparkline chars fixed), pruning limits added. |
| [sessions.md](sessions.md) | reviewed | Session identity, tmux integration, launch configs, run subcommand. DomainStore streaming state added. |
| [hot-reload.md](hot-reload.md) | reviewed | Trigger mechanism, state survival/reset, stable/reloadable boundary. Protocol validation order fixed. |
| [themes.md](themes.md) | reviewed | Color system, palette generation, semantic colors, theme switching. Light mode color values corrected. |
| [panels.md](panels.md) | reviewed | Side panel system: cycling panels, toggle panels, panel modes, view store coordination. |
| [search.md](search.md) | reviewed | Search invocation, state machine, searchable content (6 block types added), highlights, navigation. |
| [filters.md](filters.md) | reviewed | VisState model, category enum, filter registry, filtersets. Cycling keys and toggle keys corrected. |
| [export.md](export.md) | reviewed | Plain-text dump format, command palette trigger, editor integration. |
| [errors.md](errors.md) | reviewed | Error blocks (always visible), application error indicator overlay. Staleness clearing behavior corrected. |

## Resolved Cross-Reference Issues

- **VisState consistency**: `visibility.md` and `filters.md` now both define VisState identically as `(visible, full, expanded)` with 5 meaningful states. Overlap is intentional — visibility covers user-facing behavior, filters covers the data model and rendering pipeline interaction.
- **Dead event types**: `ResponseSSEEvent` and `ResponseNonStreamingEvent` confirmed as dead code in `events.md`. No other specs reference them.
- **Category count**: All specs agree on 6 categories (USER, ASSISTANT, TOOLS, SYSTEM, METADATA, THINKING). Older docs referencing 7 categories (with separate BUDGET/HEADERS) are stale.
- **Filterset keys**: `visibility.md`, `filters.md`, and `navigation.md` now all agree: `=`/`-` for cycling, number keys for toggle. F1-F9 are display-only (unimplemented).
- **Toggle analytics keys**: `filters.md` corrected to match `visibility.md`: lowercase `q/w/e/r/t/y`, not Alt+modifier.

## Remaining Items for Iteration 2

- **System prompt diffing**: `formatting.md` notes the content-hashing/diffing system described in ARCHITECTURE.md appears removed from codebase. Needs definitive confirmation of whether this is permanent.
- **panels.md**: InfoPanel visibility mechanism needs deeper review (widget-level reaction vs app-level sync). SETTINGS_FIELDS emptiness confirmed but may gain fields.
- **sessions.md**: Multi-session architecture doc is a proposal — no implementation exists yet. Tab scaffolding may appear.
- **analytics.md**: Tool economics (`get_tool_economics()`) exists but has no panel consumer. Lane counts populated outside core analytics store.
- **export.md**: macOS-only editor integration — needs clarification on whether this is deliberate scope or technical limitation.
- **errors.md**: Exception items appear to never be cleared during a session — needs definitive confirmation.
- **Nitpick pass**: Several specs could benefit from consistent terminology and cross-reference links.
