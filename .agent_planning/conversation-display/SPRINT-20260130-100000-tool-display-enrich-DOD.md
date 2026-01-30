# Definition of Done: tool-display-enrich
Generated: 2026-01-30-100000
Status: READY FOR IMPLEMENTATION
Plan: SPRINT-20260130-100000-tool-display-enrich-PLAN.md

## Acceptance Criteria

### ToolUseBlock detail field
- [ ] `ToolUseBlock` dataclass has `detail: str = ""` field
- [ ] Existing ToolUseBlock construction without `detail` argument works (default)
- [ ] All existing tests pass unchanged

### Tool-specific detail extraction
- [ ] `_tool_detail("Read", {"file_path": "/a/b/c/d/file.ts"})` returns front-ellipsed path
- [ ] `_tool_detail("Read", {})` returns `""` (no file_path key)
- [ ] `_tool_detail("Skill", {"skill": "commit"})` returns `"commit"`
- [ ] `_tool_detail("Skill", {})` returns `""`
- [ ] `_tool_detail("Bash", {"command": "git status"})` returns `"git status"`
- [ ] `_tool_detail("Bash", {"command": "very long command..."})` truncates with ellipsis
- [ ] `_tool_detail("Bash", {"command": "line1\nline2"})` returns only first line
- [ ] `_tool_detail("UnknownTool", {"anything": "value"})` returns `""`
- [ ] `format_request()` populates `detail` field on ToolUseBlock for Read, Skill, Bash tools

### Rendering
- [ ] `_render_tool_use` with non-empty detail: output contains detail between name and bytes
- [ ] `_render_tool_use` with empty detail: output identical to current behavior
- [ ] Detail text styled dim

### Tests
- [ ] Unit tests for `_tool_detail` helper (at least 6 cases covering all three tools + unknown + edge cases)
- [ ] Unit test for `_render_tool_use` with detail
- [ ] All existing tests still pass
