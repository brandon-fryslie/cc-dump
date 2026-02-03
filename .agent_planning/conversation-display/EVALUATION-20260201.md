# Evaluation: XML Tag Parsing and Filtering
Generated: 2026-02-01

## Verdict: CONTINUE

## Current State

The cc-dump TUI displays text content blocks (TextContentBlock, TrackedContentBlock, TextDeltaBlock) as plain text. No XML/markup parsing exists anywhere in the pipeline. Content containing XML tags like `<system-reminder>...</system-reminder>` is rendered as raw text with no structural awareness.

## What Needs to Happen

Parse XML-like tags in text content, track their extents, colorize matched open/close tags, and provide a filter toggle ('x') to collapse/expand XML blocks.

## Architecture Fit

The existing pipeline is well-suited for this:

1. **Parsing layer**: Should happen in `formatting.py` — the IR stage. XML tags in text content need to be detected and the text split into segments: plain text segments and XML-tagged segments. This creates new FormattedBlock types (or enriches existing ones).

2. **Rendering layer**: `tui/rendering.py` already handles per-block expand/collapse (TrackedContentBlock, TurnBudgetBlock). The XML block rendering follows the same pattern.

3. **Filter system**: The `active_filters` dict in `app.py` already has 8 filters. Adding `"xml"` with keybinding `x` follows the exact same pattern.

4. **Click expand**: `ConversationView.on_click()` already supports per-block expansion via `_expanded_overrides`. XML blocks can use the same mechanism.

## Key Design Decision: Where to Parse

**Option A: Parse at formatting time** — Split text content in `format_request()` into `XmlTaggedBlock` segments during IR creation. Pros: Clean separation, blocks are self-contained. Cons: Adds complexity to format_request, changes block list structure.

**Option B: Parse at render time** — Keep TextContentBlock unchanged, parse XML tags in `_render_text_content()`. Pros: No IR changes, simpler first step. Cons: Repeated parsing on every render, harder to track tag identity for color assignment.

**Recommended: Option A** — Parse at formatting time. This respects the existing architecture where formatting.py produces structured IR and rendering.py just displays it. Tag color assignment needs to be stable across re-renders, which means it belongs in the formatting/tracking stage.

## Risks

- **Nested XML tags**: Content may have nested tags. Need clear handling (color innermost, or show nesting depth).
- **Malformed XML**: Tags may not be properly closed. Need graceful degradation.
- **Performance**: Long system prompts with many XML blocks could create many small blocks. The virtual rendering (Line API) handles this well since only viewport lines render.
- **Streaming text**: TextDeltaBlock content accumulates incrementally. XML tags may span multiple deltas. Parsing should happen at finalization, not per-delta.
