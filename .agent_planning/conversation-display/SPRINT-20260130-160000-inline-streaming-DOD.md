# Definition of Done: inline-streaming
Generated: 2026-01-30T16:00:00
Status: PARTIALLY READY
Plan: SPRINT-20260130-160000-inline-streaming-PLAN.md

## Acceptance Criteria

### Streaming turn lifecycle
- [ ] ConversationView.begin_streaming_turn() creates empty streaming TurnData
- [ ] ConversationView.append_streaming_block() handles TextDeltaBlock (buffer + render delta tail)
- [ ] ConversationView.append_streaming_block() handles non-delta blocks (flush + render + stable prefix)
- [ ] ConversationView.finalize_streaming_turn() consolidates TextDeltaBlocks → TextContentBlocks
- [ ] Finalize re-renders full turn from consolidated blocks
- [ ] Finalize returns consolidated block list

### Visual behavior
- [ ] Streaming content appears directly in ConversationView (no separate panel)
- [ ] Streaming text grows visually as tokens arrive
- [ ] Follow mode auto-scrolls during streaming
- [ ] After finalize, content looks identical to a non-streaming turn

### StreamingRichLog removal
- [ ] StreamingRichLog class deleted from widget_factory.py
- [ ] No StreamingRichLog in app.py compose, hot-reload, or widget accessors
- [ ] StreamingRichLog CSS removed from styles.css
- [ ] No remaining references to StreamingRichLog in codebase

### Event handler integration
- [ ] handle_response_headers routes to ConversationView streaming methods
- [ ] handle_response_event routes to ConversationView streaming methods
- [ ] handle_response_done calls finalize_streaming_turn()
- [ ] No widgets["streaming"] references in event_handlers.py

### State management
- [ ] get_state() preserves streaming turn state (blocks, delta buffer, is_streaming)
- [ ] restore_state() restores streaming turn correctly
- [ ] Hot-reload mid-stream preserves content

### Tests
- [ ] Unit tests for streaming turn lifecycle (begin → append → finalize)
- [ ] Unit tests for delta buffer rendering (strips grow, stable prefix preserved)
- [ ] Unit tests for consolidation (TextDeltaBlock → TextContentBlock)
- [ ] All existing tests pass
- [ ] No test references StreamingRichLog
