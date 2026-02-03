# Sprint: xml-tag-parsing - XML Tag Parsing and Filtering
Generated: 2026-02-01
Confidence: HIGH: 5, MEDIUM: 1, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Parse XML tags in text content, colorize matched open/close tags, and add a collapsible XML filter toggle ('x') with click-to-expand support.

## Scope
**Deliverables:**
- XML tag parser that detects `<tag>...</tag>` structures in text content
- `XmlTaggedBlock` FormattedBlock type for XML-tagged content segments
- Colorized rendering of matched open/close tags (same color per tag pair)
- Filter toggle 'x' for XML: OFF = collapsed one-liner, ON = full content
- Click-to-expand individual XML blocks

## Work Items

### P0: XML Tag Parser (HIGH)
**What:** Create a parser function in `formatting.py` that splits text content containing XML tags into segments: plain text + XML-tagged regions.

**Acceptance Criteria:**
- [ ] Parser detects `<tagname>...</tagname>` patterns (including `<tag attr="...">`)
- [ ] Returns list of segments: `("text", content)` or `("xml", tag_name, inner_content, full_text)`
- [ ] Handles nested tags (outer tag includes inner tags in its content)
- [ ] Gracefully handles malformed/unclosed tags (treat as plain text)
- [ ] Unit tests for parser covering: simple tags, nested tags, self-closing, malformed, no tags

**Technical Notes:**
- Use a simple state machine or regex approach, NOT a full XML parser
- Match angle-bracket tags only: `<name>` ... `</name>` where name is `[a-zA-Z_][\w-]*`
- Self-closing tags (`<br/>`) can be treated as plain text or ignored
- Tags spanning multiple lines are common (system-reminder blocks are multi-line)

### P1: XmlTaggedBlock IR Type (HIGH)
**What:** Add a new `XmlTaggedBlock` FormattedBlock dataclass and integrate it into the formatting pipeline.

**Acceptance Criteria:**
- [ ] `XmlTaggedBlock(tag_name, content, color_idx)` dataclass in `formatting.py`
- [ ] `format_request()` splits TextContentBlock text through the XML parser
- [ ] When XML tags found, produces sequence: [TextContentBlock, XmlTaggedBlock, TextContentBlock, ...]
- [ ] Color assignment uses a per-tag-name cycling scheme (same tag_name = same color)
- [ ] Non-XML text segments remain as TextContentBlock

**Technical Notes:**
- XML tag color assignment: maintain a `xml_tag_colors: dict[str, int]` in formatting state
- Each unique tag_name gets a stable color index (cycling through palette)
- This happens inside `format_request()` wherever TextContentBlock is currently created
- Also needs to handle TrackedContentBlock content (the `content` field has XML in it)

### P2: XML Block Renderer (HIGH)
**What:** Add rendering for XmlTaggedBlock in `tui/rendering.py` with colorized tags and collapse/expand support.

**Acceptance Criteria:**
- [ ] `_render_xml_tagged_block()` function registered in BLOCK_RENDERERS
- [ ] Open and close tags rendered in matching color from palette
- [ ] When xml filter OFF: shows `<tag_name>first few words...</tag_name>` on one line
- [ ] When xml filter ON: shows full content with colored open/close tags
- [ ] Supports per-block expand override (like TrackedContentBlock)

**Technical Notes:**
- Collapsed view: `<system-reminder>A few words from the beginning...</system-reminder>`
  - Tag names in color, content preview truncated with "..."
- Expanded view: Full content with indentation, tag names in same color
- Add to BLOCK_FILTER_KEY: `"XmlTaggedBlock": "xml"`
- Add to _EXPANDABLE_BLOCK_TYPES

### P3: Filter Toggle Integration (HIGH)
**What:** Add 'x' keybinding for XML filter toggle, wire into active_filters and footer.

**Acceptance Criteria:**
- [ ] `show_xml = reactive(False)` in `CcDumpApp`
- [ ] Binding `"x"` → `"toggle_xml"` with description `"|x|ml"`
- [ ] `active_filters` dict includes `"xml": self.show_xml`
- [ ] Footer shows XML toggle state with indicator color
- [ ] `_rerender_if_mounted()` called on change

**Technical Notes:**
- In `app.py`: add reactive property, binding, action handler, watcher (follows exact pattern of show_tools)
- In `custom_footer.py`: add to `_filter_names` list: `("toggle_xml", "xml")`
- In `palette.py`: add "xml" to indicator colors (needs a color slot)
- In `rendering.py`: add to FILTER_INDICATORS

### P4: Click-to-Expand XML Blocks (HIGH)
**What:** Make XML blocks clickable to toggle expand/collapse per-block, same as TrackedContentBlock.

**Acceptance Criteria:**
- [ ] Clicking an XmlTaggedBlock line toggles its expand state
- [ ] Per-block override stored in `_expanded_overrides`
- [ ] Works independently of the global 'x' toggle
- [ ] Arrow indicator (▶/▼) shown on collapsed/expanded blocks

**Technical Notes:**
- In `widget_factory.py`: add "XmlTaggedBlock" to `_is_expandable_block()` check
- The existing `_toggle_block_expand()` logic handles the rest automatically
- Expand override uses same `(turn_index, block_index)` key system

### P5: Streaming Finalization (MEDIUM)
**What:** Ensure XML parsing works correctly for streaming content that gets finalized.

**Acceptance Criteria:**
- [ ] When streaming text is finalized (TextDeltaBlocks → TextContentBlock), XML tags are detected
- [ ] Finalized turn shows properly parsed XML blocks

**Technical Notes:**
- `finalize_streaming_turn()` in widget_factory.py already consolidates deltas into TextContentBlock
- The XML parsing should happen when the TextContentBlock is created, not during streaming
- May need to re-parse blocks at finalization time
- **Unknown**: Need to verify exactly how finalization creates the TextContentBlock — does it go through format_request() or is it constructed directly?

#### Unknowns to Resolve
- How finalize_streaming_turn creates the consolidated block
- Whether XML parsing should happen in finalization or in a re-render pass

#### Exit Criteria
- Read finalize_streaming_turn() code and determine integration point

## Dependencies
- None — this is greenfield functionality on the existing pipeline

## Risks
- **Nested XML complexity**: Mitigated by treating nesting as "outer tag contains everything including inner tags"
- **Performance with many small blocks**: Mitigated by virtual rendering (Line API)
- **Hot-reload safety**: Use class name strings in BLOCK_RENDERERS, not isinstance
