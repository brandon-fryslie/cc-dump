# cc-dump Specification Index

## Resolved Cross-Reference Issues

- **VisState consistency**: `visibility.md` and `filters.md` now both define VisState identically as `(visible, full, expanded)` with 5 meaningful states. Overlap is intentional — visibility covers user-facing behavior, filters covers the data model and rendering pipeline interaction.
- **Dead event types**: `ResponseSSEEvent` and `ResponseNonStreamingEvent` confirmed as dead code in `events.md`. No other specs reference them.
- **Category count**: All specs agree on 6 categories (USER, ASSISTANT, TOOLS, SYSTEM, METADATA, THINKING). Older docs referencing 7 categories (with separate BUDGET/HEADERS) are stale.
- **Filterset keys**: `visibility.md`, `filters.md`, and `navigation.md` now all agree: `=`/`-` for cycling, number keys for toggle. F1-F9 are display-only (unimplemented).
- **Toggle analytics keys**: `filters.md` corrected to match `visibility.md`: lowercase `q/w/e/r/t/y`, not Alt+modifier.
- **Stale module paths**: `hot-reload.md` and `errors.md` now agree that staleness reports use relative paths (e.g., `pipeline/proxy.py`), not bare filenames. `errors.md` corrected: view_store extracts basename only via `s.split("/")[-1]`.
- **ALWAYS_VISIBLE constant**: `errors.md` now cross-references the `ALWAYS_VISIBLE` constant used in the rendering pipeline for `None`-category blocks.
- **Error indicator width**: `errors.md` corrected from "single cell" to "4-cell strip" matching `_COLLAPSED_WIDTH = 4`.
- **System prompt diffing**: Definitively confirmed as permanently absent. No `TrackedContentBlock`, no hash computation, no diff generation exists anywhere in the codebase. `ProviderRuntimeState` carries no system prompt history. `formatting.md` (draft-3) documents this as settled.
- **Click-to-expand**: `visibility.md` and `filters.md` corrected. `on_click` on `ConversationView` only stores click position for double-click text selection — it does NOT toggle block expansion. Per-block expansion overrides are set programmatically (search reveal, location navigation).
- **Export missing block types**: `export.md` now documents 4 block types (`NewSessionBlock`, `ThinkingBlock`, `ConfigContentBlock`, `HookOutputBlock`) that have no `BLOCK_WRITERS` entry and produce fallback output.
- **Export platform scope**: `export.md` clarifies macOS-only editor integration is a deliberate scope choice, not a technical limitation.
- **Multi-session implementation**: `sessions.md` rewritten — per-session `DomainStore` instances, `ConversationView`/`TabPane` creation, session key resolution, and tab-based tracking all exist in the code. The "no implementation" claim was wrong.
- **ResponseDoneEvent scope**: `events.md` corrected — emitted for streaming AND synthetic interceptor paths, not streaming only.
- **`sse_event_to_dict()` usage**: `events.md` corrected — unused in production code, only exercised by tests.

## Iteration 3 Status

All 17 spec files have been updated and cross-reviewed. Key improvements this iteration:

- **events.md**: 2 corrections (unused function, synthetic path emission)
- **formatting.md**: System prompt diffing confirmed permanently absent
- **rendering.md**: StopReasonBlock FC rendering corrected, stop reason hints updated
- **visibility.md**: Click-to-expand overclaim removed, expandability algorithm corrected
- **filters.md**: BLOCK_CATEGORY mapping added (28 types), click references corrected
- **proxy.md**: No changes needed — already accurate
- **recording.md**: 11 corrections, marked verified
- **analytics.md**: Tool correlation, TypedDict tables, legacy query methods added
- **navigation.md**: 7 corrections to scroll/follow mechanics
- **search.md**: Debounce, text cache, highlight/reveal behavior added
- **panels.md**: Extensive panel-by-panel updates, visibility mechanisms documented
- **cli.md**: 5 corrections to startup/shutdown details
- **hot-reload.md**: 14 updates including exact module count, alias algorithm, widget categories
- **sessions.md**: Major rewrite — multi-session implementation documented
- **themes.md**: Runtime resolution, palette init, color fallbacks added
- **errors.md**: Request guards, path format, rendering dispatch corrected
- **export.md**: Platform scope, programmatic API, 4 missing block types documented

## Remaining Items for Iteration 4

- **Nitpick pass**: Remove fragile line number references from `rendering.md`. Remove specific "31 block types" count (will drift).
- **Search `q` key discrepancy**: Footer in SEARCH_EDIT mode shows `q=exit(restore)` but `q` inserts as printable character. Both `search.md` and `navigation.md` note this — it's a code bug, not a spec issue.
- **`_compute_expandable` naming**: `visibility.md` now correctly describes the expandability logic as inline within `_render_block_tree` rather than referencing a non-existent named function.
- **Tool economics consumer**: `analytics.md` correctly notes `get_tool_economics()` exists but has no panel consumer. This is a feature gap, not a spec issue.
