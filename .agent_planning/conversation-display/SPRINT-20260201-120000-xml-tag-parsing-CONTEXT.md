# Implementation Context: XML Tag Parsing and Filtering

## Architecture Overview

The cc-dump pipeline is: `API JSON → formatting.py (IR) → rendering.py (Rich Text) → widget_factory.py (Strips)`

XML tag parsing fits into this pipeline at the **formatting stage**, producing `XmlTaggedBlock` IR nodes that the rendering stage converts to colored Rich Text.

## File-by-File Implementation Guide

### 1. `src/cc_dump/formatting.py`

**Add XmlTaggedBlock dataclass** (after TextContentBlock, ~line 97):
```python
@dataclass
class XmlTaggedBlock(FormattedBlock):
    """An XML-tagged content region."""
    tag_name: str = ""      # e.g. "system-reminder"
    content: str = ""       # Inner content between tags
    color_idx: int = 0      # Color index for tag colorization
    indent: str = "    "
```

**Add XML parser function** (new function, after `_make_tracked_block`):
```python
def parse_xml_segments(text: str) -> list[tuple]:
    """Parse text into segments of plain text and XML-tagged regions.

    Returns list of:
      ("text", content_str)
      ("xml", tag_name, inner_content)
    """
```

Pattern to match: `<tag_name[^>]*>` ... `</tag_name>` where content can span multiple lines.

Use a simple approach:
1. Find all `<tag_name>` opening tags with regex
2. For each, find matching `</tag_name>`
3. Extract segments between/around matches
4. Handle nesting by matching outermost tags first

**Integrate into format_request()**: Where TextContentBlock is created (~lines 415, 428), if the text contains `<`, run it through `parse_xml_segments()` and emit mixed TextContentBlock + XmlTaggedBlock sequence.

**State for XML tag colors**: Add `xml_tag_colors: dict[str, int]` and `xml_next_color: int` to the state dict. Each unique tag_name gets a stable color.

### 2. `src/cc_dump/tui/rendering.py`

**Add renderer function**:
```python
def _render_xml_tagged_block(block: XmlTaggedBlock, filters: dict, *, expanded: bool | None = None) -> Text | None:
    is_expanded = expanded if expanded is not None else filters.get("xml", False)
    fg, bg = TAG_STYLES[block.color_idx % len(TAG_STYLES)]
    tag_style = "bold {} on {}".format(fg, bg)

    if is_expanded:
        # Full content with colored tags
        t = Text(block.indent)
        t.append("<{}>".format(block.tag_name), style=tag_style)
        t.append("\n")
        t.append(_indent_text(block.content, block.indent + "  "))
        t.append("\n" + block.indent)
        t.append("</{}>".format(block.tag_name), style=tag_style)
        return t
    else:
        # Collapsed: one-line preview
        preview = block.content.split("\n")[0][:60]
        if len(block.content) > len(preview):
            preview += "..."
        t = Text(block.indent)
        t.append("<{}>".format(block.tag_name), style=tag_style)
        t.append(preview)
        t.append("</{}>".format(block.tag_name), style=tag_style)
        return t
```

**Register in BLOCK_RENDERERS** (~line 298):
```python
"XmlTaggedBlock": _render_xml_tagged_block,
```

**Register in BLOCK_FILTER_KEY** (~line 326):
```python
"XmlTaggedBlock": None,  # Always visible, but collapse/expand controlled by "xml" filter
```

**Add to _EXPANDABLE_BLOCK_TYPES** (~line 59):
```python
_EXPANDABLE_BLOCK_TYPES = frozenset({"TrackedContentBlock", "TurnBudgetBlock", "XmlTaggedBlock"})
```

**Add to imports** (~line 10): Add `XmlTaggedBlock` to the import list.

**Add to FILTER_INDICATORS** (~line 42): Add `"xml"` entry.

### 3. `src/cc_dump/tui/app.py`

**Add reactive + binding** (follows exact pattern of existing toggles):
```python
# In BINDINGS list:
Binding("x", "toggle_xml", "|x|ml", show=True),

# Reactive property:
show_xml = reactive(False)

# In active_filters:
"xml": self.show_xml,

# Action handler:
def action_toggle_xml(self):
    self.show_xml = not self.show_xml

# Watcher:
def watch_show_xml(self, value):
    self._rerender_if_mounted()
```

### 4. `src/cc_dump/tui/custom_footer.py`

**Add to _filter_names** (~line 72):
```python
("toggle_xml", "xml"),
```

### 5. `src/cc_dump/palette.py`

**Add "xml" indicator color**. Check current indicator colors and add one for XML. The indicator colors are defined in `_INDICATOR_COLORS` list.

### 6. `src/cc_dump/tui/widget_factory.py`

**Add to _is_expandable_block()**: Add "XmlTaggedBlock" to the expandable type check.

No other changes needed — the existing `_toggle_block_expand()` and `on_click()` handle the rest via the type name check.

## Hot-Reload Considerations

- `formatting.py` is reloadable — new XmlTaggedBlock class will be picked up
- `rendering.py` is reloadable — new renderer registered on reload
- `app.py` is a stable boundary — uses `import cc_dump.formatting` pattern
- `widget_factory.py` is reloadable — type name check works across reloads

## Test Strategy

- Unit tests for `parse_xml_segments()` — pure function, easy to test
- Test cases: simple tags, nested, malformed, no tags, multi-line content
- Integration test: feed text with XML through format_request(), verify XmlTaggedBlock produced
- Rendering test: verify render output for collapsed/expanded states
