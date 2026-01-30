# Sprint: tool-display-enrich - Tool Display Enrichment
Generated: 2026-01-30-100000
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION
Source: EVALUATION-20260130.md

## Sprint Goal
Enrich tool_use block display with tool-specific detail text: ellipsed file paths for Read, skill name for Skill, command preview for Bash.

## Scope
**Deliverables:**
- ToolUseBlock gains an optional `detail` field rendered after the tool name
- Read tool extracts `file_path` and front-ellipses it
- Skill tool extracts `skill` field
- Bash tool extracts `command` field (truncated preview)
- All displayed inline in existing tool_use renderer

## Work Items

### P1 [HIGH] Add `detail` field to ToolUseBlock

**Dependencies**: None
**Spec Reference**: Roadmap Items 1, 5, 6 | **Status Reference**: EVALUATION-20260130.md "Item 1/5/6"

#### Description
Add an optional `detail: str = ""` field to the `ToolUseBlock` dataclass. When non-empty, the renderer appends it after the tool name. This is a single field that all three tool-specific enrichments populate.

The ONE TYPE PER BEHAVIOR principle applies here: Read/Skill/Bash enrichment is the SAME behavior (extract a string from input, display it). They differ only in which key they extract and how they format it. One field, three extraction rules.

#### Acceptance Criteria
- [ ] `ToolUseBlock` has a `detail: str = ""` field
- [ ] Existing code that creates `ToolUseBlock` without `detail` continues to work (default empty)
- [ ] No existing tests break

#### Technical Notes
- Add field at formatting.py:96 after `msg_color_idx`
- Default `""` ensures backward compatibility

---

### P1 [HIGH] Extract tool-specific detail during formatting

**Dependencies**: "Add detail field to ToolUseBlock"
**Spec Reference**: Roadmap Items 1, 5, 6 | **Status Reference**: EVALUATION-20260130.md "Item 1/5/6"

#### Description
In `format_request()` at the `tool_use` branch (formatting.py:359-363), after extracting `name` and `input_size`, compute a detail string based on tool name:

- **Read**: Extract `file_path` from `tool_input`. Front-ellipse to `...last/two/segments.ext` (max ~40 chars).
- **Skill**: Extract `skill` from `tool_input`. Show as-is.
- **Bash**: Extract `command` from `tool_input`. Show first line, truncated to ~60 chars.

Use a helper function `_tool_detail(name, tool_input) -> str` to keep the formatting branch clean.

#### Acceptance Criteria
- [ ] Read tool_use blocks show `...path/to/file.ext` detail when `file_path` present in input
- [ ] Skill tool_use blocks show skill name when `skill` present in input
- [ ] Bash tool_use blocks show command preview (first line, truncated) when `command` present in input
- [ ] Tools with no recognized detail fields show empty detail (no regression)
- [ ] Unit test: `_tool_detail("Read", {"file_path": "/Users/foo/bar/baz/file.ts"})` returns `"...bar/baz/file.ts"`
- [ ] Unit test: `_tool_detail("Bash", {"command": "git status && git diff"})` returns `"git status && git diff"`
- [ ] Unit test: `_tool_detail("Skill", {"skill": "commit"})` returns `"commit"`

#### Technical Notes
- Front-ellipsis algorithm: split path on `/`, take last N segments that fit in ~40 chars, prepend `...`
- Bash truncation: take first line of `command`, truncate at 60 chars with `...` suffix if longer
- The `tool_input` dict is already parsed at formatting.py:361 (`cblock.get("input", {})`) -- just pass it through
- Do NOT store the full `input` dict on the block -- only the extracted detail string (minimizes IR size)

---

### P1 [HIGH] Render detail in tool_use renderer

**Dependencies**: "Extract tool-specific detail during formatting"
**Spec Reference**: Roadmap Items 1, 5, 6 | **Status Reference**: EVALUATION-20260130.md "Item 1/5/6"

#### Description
Update `_render_tool_use()` in rendering.py to append `block.detail` when non-empty.

Current output: `  [tool_use] Read (243 bytes)`
New output: `  [tool_use] Read ...bar/baz/file.ts (243 bytes)`

The detail appears between the tool name and the byte count, styled dim to avoid visual clutter.

#### Acceptance Criteria
- [ ] Tool use blocks with non-empty detail show detail between name and byte count
- [ ] Tool use blocks with empty detail render identically to current behavior
- [ ] Detail text is styled `dim` to distinguish from tool name
- [ ] Unit test: render a ToolUseBlock with detail and verify output contains the detail string

#### Technical Notes
- rendering.py:162 currently has `t.append(" {} ({} bytes)".format(block.name, block.input_size))`
- Change to: append name, then if detail: append detail in dim style, then append byte count
- No filter logic changes needed -- detail is part of the tool_use line, controlled by same "tools" filter

## Dependencies
- No external sprint dependencies
- Internal ordering: field addition -> extraction logic -> rendering

## Risks
- **Low**: Front-ellipsis edge cases (root paths, Windows paths, empty paths). Mitigate with defensive code and tests.
- **Low**: Bash commands with newlines. Mitigate by taking only the first line.
