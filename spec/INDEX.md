# cc-dump Specification Index

## Resolved Cross-Reference Issues

- **VisState consistency**: `visibility.md` and `filters.md` now both define VisState identically as `(visible, full, expanded)` with 5 meaningful states. Overlap is intentional — visibility covers user-facing behavior, filters covers the data model and rendering pipeline interaction.
- **Dead event types**: `ResponseSSEEvent` and `ResponseNonStreamingEvent` confirmed as dead code in `events.md`. No other specs reference them.
- **Category count**: All specs agree on 6 categories (USER, ASSISTANT, TOOLS, SYSTEM, METADATA, THINKING). Older docs referencing 7 categories (with separate BUDGET/HEADERS) are stale.
- **Filterset keys**: `visibility.md`, `filters.md`, and `navigation.md` now all agree: `=`/`-` for cycling, number keys for toggle. F1-F9 are display-only (unimplemented).
- **Toggle analytics keys**: `filters.md` corrected to match `visibility.md`: lowercase `q/w/e/r/t/y`, not Alt+modifier.
- **Stale module paths**: `hot-reload.md` and `errors.md` now agree that staleness reports use relative paths (e.g., `pipeline/proxy.py`), not bare filenames.
- **ALWAYS_VISIBLE constant**: `errors.md` now cross-references the `ALWAYS_VISIBLE` constant used in the rendering pipeline for `None`-category blocks.
- **Error indicator width**: `errors.md` corrected from "single cell" to "4-cell strip" matching `_COLLAPSED_WIDTH = 4`.

## Remaining Items for Iteration 3

- **System prompt diffing**: `formatting.md` notes the content-hashing/diffing system described in ARCHITECTURE.md appears removed from codebase. Needs definitive confirmation of whether this is permanent.
- **panels.md**: InfoPanel visibility mechanism needs deeper review (widget-level reaction vs app-level sync). SETTINGS_FIELDS emptiness confirmed but may gain fields.
- **sessions.md**: Multi-session architecture doc is a proposal — no implementation exists yet. Tab scaffolding may appear.
- **analytics.md**: Tool economics (`get_tool_economics()`) exists but has no panel consumer. Lane counts populated outside core analytics store.
- **export.md**: macOS-only editor integration — needs clarification on whether this is deliberate scope or technical limitation.
- **Nitpick pass**: Several specs could benefit from consistent terminology and cross-reference links.
- **Missing "why" sections**: Some specs describe mechanism without motivation — a pass to add rationale for key design decisions would improve utility.
