# Sprint: formatting-ir - Formatting Intermediate Representation
Generated: 2026-01-24
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Complete the FormattedBlock IR by creating the ANSI renderer and updating display.py to use the block→string chain.

## Scope
**Deliverables:**
- `formatting_ansi.py` — renders FormattedBlock lists to ANSI strings
- Updated `display.py` — calls formatting → ANSI renderer chain
- Output identical to pre-refactor behavior

## Work Items

### P0: Create formatting_ansi.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Renders every FormattedBlock subclass to the same ANSI output the old formatting.py produced
- [ ] `render_blocks(blocks: list[FormattedBlock]) -> str` returns full ANSI string for request blocks
- [ ] `render_block(block: FormattedBlock) -> str` handles individual block rendering
- [ ] TextDeltaBlock returns raw text (no newline) for inline streaming
- [ ] Uses colors.py constants (single source of truth for colors)

**Technical Notes:**
- Match function: dispatch on block type via isinstance checks
- MSG_COLORS list for cycling message colors matches formatting.py's MSG_COLOR_CYCLE=6
- TrackedContentBlock rendering: format tag with TAG_COLORS, show content/diff based on status
- DiffBlock: compute diff_lines from make_diff_lines() if not pre-computed

### P1: Update display.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `handle()` calls `format_request()` → gets blocks → calls `render_blocks()` → writes to stdout
- [ ] `handle()` calls `format_response_event()` → gets blocks → renders each appropriately
- [ ] TextDeltaBlock writes inline (no newline), all others get newline
- [ ] response_start/response_done/error/proxy_error/log events produce identical output
- [ ] Hot-reload still works (no module-level mutable state)

**Technical Notes:**
- Import from formatting_ansi instead of formatting for render functions
- Keep the event dispatch structure, just change what happens inside each branch
- response_start/error/proxy_error/log can produce blocks directly in display.py or use simple string formatting

### P2: Verify output identity
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Running `cc-dump --port 3344` produces visually identical output to pre-refactor
- [ ] Streaming text appears inline without extra newlines
- [ ] System prompt tracking (new/ref/changed) renders correctly with tags and diffs

## Dependencies
- formatting.py refactor is DONE (FormattedBlock dataclasses exist)

## Risks
- None significant. This is a mechanical translation of existing output logic.
