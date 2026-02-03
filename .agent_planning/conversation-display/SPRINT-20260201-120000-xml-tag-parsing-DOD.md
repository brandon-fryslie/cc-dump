# Definition of Done: XML Tag Parsing and Filtering

## Functional Requirements
- [ ] XML tags (`<name>...</name>`) in text content are detected and parsed
- [ ] Matched open/close tags are rendered in the same color
- [ ] 'x' key toggles XML filter between collapsed and expanded views
- [ ] Collapsed view: `<tag>A few words...</tag>` (one line per XML block)
- [ ] Expanded view: Full content with all lines visible
- [ ] Clicking an XML block toggles its individual expand/collapse state
- [ ] Footer shows XML toggle state with colored indicator
- [ ] Malformed tags degrade gracefully to plain text
- [ ] Nested tags handled (outer tag shows full content including inner tags)

## Technical Requirements
- [ ] `XmlTaggedBlock` dataclass in `formatting.py`
- [ ] XML parser function with unit tests
- [ ] Renderer in `rendering.py` registered in BLOCK_RENDERERS
- [ ] Filter key "xml" in BLOCK_FILTER_KEY
- [ ] Hot-reload safe (class name strings, module-level imports)
- [ ] No performance regression on large conversations

## Verification
- [ ] `uv run pytest` passes with no failures
- [ ] Manual verification: system-reminder XML blocks display correctly
- [ ] Filter toggle works: 'x' switches between collapsed/expanded
- [ ] Click-to-expand works on individual XML blocks
- [ ] Colors are consistent (same tag name = same color across turns)
