# Definition of Done: message-collapse
Generated: 2026-02-03T18:00:00
Status: READY FOR IMPLEMENTATION
Plan: SPRINT-20260203-180000-message-collapse-PLAN.md

## Acceptance Criteria

### Filter State and Bindings (CcDumpApp)
- [ ] `show_user_messages = reactive(False)` on CcDumpApp
- [ ] `show_assistant_messages = reactive(False)` on CcDumpApp
- [ ] Key binding `u` toggles user message expand
- [ ] Key binding `d` toggles assistant message expand
- [ ] `active_filters` includes `"user": bool` and `"assistant": bool`
- [ ] Watchers call `_rerender_if_mounted()` on change
- [ ] Action handlers `action_toggle_user_messages()` and `action_toggle_assistant_messages()` exist

### Rendering: Collapse Logic
- [ ] `render_blocks()` tracks current role from RoleBlock
- [ ] TextContentBlock after USER role: first 2 lines only when `filters["user"]` is False
- [ ] TextContentBlock after ASSISTANT role: first 2 lines only when `filters["assistant"]` is False
- [ ] Right arrow (`\u25b6`) prepended to collapsed text when >2 lines
- [ ] Down arrow (`\u25bc`) prepended to expanded text when >2 lines
- [ ] No arrow when message has <=2 lines
- [ ] Messages with exactly 1 or 2 lines show full content regardless of filter state
- [ ] Filter indicators (colored bar) appear on role-filtered content

### Filter Key Relevance
- [ ] `TurnData.compute_relevant_keys()` adds `"user"` for turns with user text content
- [ ] `TurnData.compute_relevant_keys()` adds `"assistant"` for turns with assistant text content
- [ ] Toggling user filter does NOT re-render assistant-only turns (and vice versa)

### Footer Integration
- [ ] `u` and `d` appear in footer with styled descriptions
- [ ] Active state background changes when toggled on
- [ ] `_build_filter_indicators()` includes `"user"` and `"assistant"` entries

### Tests
- [ ] 7+ new tests covering collapse/expand, indicators, independence
- [ ] All existing tests pass (`uv run pytest`)
- [ ] Lint passes (`just lint`)

### Verification
- [ ] Manual: Load conversation with user and assistant messages >2 lines
- [ ] Manual: Press `u` -- user messages expand, assistant stay collapsed
- [ ] Manual: Press `d` -- assistant messages expand independently
- [ ] Manual: Messages with <=2 lines never show arrow or collapse
- [ ] Manual: Filter toggle is responsive (<50ms even on large conversations)
