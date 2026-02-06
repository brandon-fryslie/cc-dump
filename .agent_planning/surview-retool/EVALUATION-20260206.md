# Evaluation: Retool cc-dump into Surview -- General-Purpose HTTP Debugger
Timestamp: 2026-02-06
Git Commit: ca5ce87

## Executive Summary
Overall: 0% complete (assessment phase, no implementation started) | Critical issues: 2 | Tests reliable: mostly (1 pre-existing failure)

The retool plan is **architecturally sound**. The codebase has clean separation between generic infrastructure (router, virtual rendering, hot-reload, palette) and LLM-specific logic (formatting, analysis, SSE parsing). The two-stage pipeline design (blocks -> Rich Text) means the IR layer can be replaced without touching the rendering engine. The main risks are in ordering and in a few hidden coupling points the user's assessment missed.

## Runtime Check Results
| Check | Status | Output |
|-------|--------|--------|
| pytest | 428 pass, 1 fail, 2 skip | Pre-existing: test_format_response_event_message_start stale assertion |
| lint (ruff) | Not run | N/A |
| TUI startup | Not tested | Live proxy not exercised |

## Missing Checks
- No automated integration test that validates "proxy captures arbitrary HTTP request/response and displays in TUI" (the core new behavior)
- No test that validates HAR recording of non-SSE responses
- No test for non-POST HTTP methods being captured (currently only POST /v1/messages is captured)

## Findings

### 1. Proxy Layer (proxy.py) -- The Critical Bottleneck
**Status**: PARTIAL (generic forwarding works, but event emission is Claude-locked)
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/proxy.py:59`
```python
if body_bytes and request_path.startswith("/v1/messages"):
```
**Issues**:
- Only emits events for POST to /v1/messages. ALL other traffic is silently forwarded with zero visibility. This is the single most important change for the retool.
- SSE parsing in `_stream_response()` (lines 114-139) assumes `data: ` prefix lines and `[DONE]` terminator -- this is Claude/OpenAI SSE format, not generic SSE. Standard SSE uses `event:` and `data:` lines per the W3C spec. The `[DONE]` sentinel is an API convention, not SSE standard.
- Non-streaming responses (lines 110-112) are forwarded but NO events are emitted (no response body capture for non-SSE responses).
- Only handles POST and GET. No PUT, DELETE, PATCH, HEAD methods. The `_proxy()` method handles them, but only `do_POST` and `do_GET` dispatch to it.

**Risk**: This file needs near-total rewrite. The generic proxy must emit events for ALL requests, not just specific paths. It must handle streaming and non-streaming responses uniformly.

### 2. Event Schema
**Status**: TIGHTLY COUPLED to Claude SSE
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/proxy.py:137`
```python
self.event_queue.put(("response_event", event_type, event))
```
**Issues**:
- The event type `"response_event"` carries Claude SSE event types (message_start, content_block_delta, etc.) as its second element. The entire downstream pipeline (formatting.py:560-591, event_handlers.py:125-178, store.py:57-78) switches on these Claude-specific event types.
- For a generic proxy, the event schema needs to change. Options: (a) emit raw SSE lines as events, (b) emit generic request/response body events, (c) emit both raw and parsed. This is an open design question.

**Ambiguity**: The plan says "simplified filters: headers (h), body (b), sse (s), follow (f)" but doesn't define the new event schema that would produce these three data categories. The current pipeline deeply assumes request body is JSON with `messages`, `system`, `tools` keys.

### 3. Formatting Layer (formatting.py)
**Status**: ~50% must be rewritten, ~50% deleted
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/formatting.py` (645 lines)
**Issues**:

**Keep (generic)**: FormattedBlock base, SeparatorBlock, HeaderBlock, HttpHeadersBlock, RoleBlock, TextContentBlock, TextDeltaBlock, DiffBlock, ImageBlock, UnknownTypeBlock, ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock, make_diff_lines(), format_request_headers(), format_response_headers(). These are ~200 lines.

**Delete**: MetadataBlock, SystemLabelBlock, TrackedContentBlock, ToolUseBlock, ToolResultBlock, StreamToolUseBlock, TurnBudgetBlock, StopReasonBlock, StreamInfoBlock, track_content(), _make_tracked_block(), format_request(), format_response_event(), format_complete_response(), _merge_tool_only_assistant_runs(), _tool_detail(). These are ~445 lines.

**New blocks needed**: RequestBodyBlock (displays JSON/form body), ResponseBodyBlock (raw or JSON response body), SSEEventBlock (individual SSE events). The plan mentions these implicitly but doesn't specify their structure.

**Hidden coupling**: `format_request()` at line 13 imports from `analysis.py`:
```python
from cc_dump.analysis import TurnBudget, compute_turn_budget, tool_result_breakdown
```
This is the ONLY import from analysis.py in the formatting layer. Once format_request() is deleted, analysis.py is completely disconnected from formatting.

### 4. Analysis Module (analysis.py)
**Status**: 100% DELETE
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/analysis.py` (375 lines)
**Issues**: Every function is Claude-specific: TurnBudget, compute_turn_budget, correlate_tools, aggregate_tools, ModelPricing, classify_model, format_model_short, ModelEconomics. No generic utility worth preserving. The only general-purpose function is `estimate_tokens()` (line 15-21), which is a `len(text) // 4` heuristic -- trivially replaceable if ever needed.

### 5. Token Counter (token_counter.py)
**Status**: 100% DELETE
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/token_counter.py` (31 lines)
**Issues**: tiktoken dependency only used here and in store.py. Removing this file and the tiktoken dependency from pyproject.toml is clean.

### 6. Store / Schema / DB Queries (store.py, schema.py, db_queries.py)
**Status**: ~80% must be rewritten
**Evidence**: Schema columns at `/Users/bmf/code/surview-py/src/cc_dump/schema.py:46-60`
```sql
turns: model, stop_reason, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, tool_names
```
**Issues**:
- The `turns` table is designed around Claude's request/response turn model. A generic HTTP debugger needs a different schema: `requests` table with method, url, status_code, request_headers, request_body, response_headers, response_body, content_type, timing.
- `tool_invocations` table is entirely LLM-specific -- DELETE.
- `blobs` table and content-addressed storage mechanism (store.py:164-188) is GENERIC and should be preserved. This is solid infrastructure.
- `turns_fts` full-text search is generic in concept but the indexed column (text_content) is LLM-specific. Would need to index request/response bodies instead.
- store.py's SQLiteWriter.on_event() (lines 34-82) switches on Claude event types (message_start, content_block_delta, etc.). Complete rewrite needed.
- db_queries.py: all 4 query functions reference Claude-specific columns. Complete rewrite.

### 7. HAR Recorder (har_recorder.py)
**Status**: ~40% LLM-specific
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/har_recorder.py:287`
```python
url="https://api.anthropic.com/v1/messages",
```
**Issues**:
- `reconstruct_message_from_events()` (lines 90-182) is 100% Claude SSE -> message reconstruction. DELETE.
- `build_har_request()` (lines 13-44) hardcodes `synthetic_body["stream"] = False`. This is Claude-specific. But the overall structure (method, url, headers, postData) is HAR 1.2 standard. REWRITE to accept actual request data instead of synthesizing.
- `build_har_response()` (lines 47-87) assumes response is a JSON message. Generic proxy must handle arbitrary content types. REWRITE.
- `HARRecordingSubscriber._commit_entry()` (line 268) calls `reconstruct_message_from_events()`. For generic proxy, this should just record raw request/response data. Major simplification opportunity -- the generic version is actually SIMPLER than the current Claude-specific version.
- HAR 1.2 format itself is standard and should be preserved. The entry structure is correct.
- Creator name (line 218): `"name": "cc-dump"` needs update to `"surview"`.

### 8. HAR Replayer (har_replayer.py)
**Status**: ~60% LLM-specific
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/har_replayer.py:72-73`
```python
if "type" not in complete_message or complete_message["type"] != "message":
```
**Issues**:
- `load_har()` validates that responses are Claude `type="message"`. For generic proxy, should accept any response.
- `convert_to_events()` (lines 105-259) synthesizes Claude SSE events from complete messages. This is the inverse of reconstruct_message_from_events(). For generic proxy, convert_to_events() should emit generic events (request_headers, request, response_headers, response_body, response_done). Major simplification.
- The load/validation logic (lines 11-102) is mostly generic HAR parsing with a Claude-specific validation check. Easy to generalize.

### 9. TUI App (tui/app.py)
**Status**: ~40% LLM-specific
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/tui/app.py:27-46` (bindings), lines 92-98 (economics/timeline panels)
**Issues**:
- Economics panel (ToolEconomicsPanel) and Timeline panel (TimelinePanel) are 100% LLM. Remove from compose() and all toggle/refresh methods.
- Bindings need remapping per plan: h(eaders), b(ody), s(se), f(ollow) instead of current h/t/s/e/m/a/c/l.
- `_process_replay_data()` (lines 184-239) references `cc_dump.formatting.MetadataBlock` by type check and calls `format_complete_response()`. Needs rewrite.
- active_filters property (lines 497-508) returns LLM filter names. Needs update.
- _handle_event_inner() (lines 418-494) routes events including "response_event" (Claude SSE). Needs update for generic events.
- Log messages reference "cc-dump" (lines 113, 653).

### 10. Rendering Layer (tui/rendering.py)
**Status**: ~30% LLM-specific
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/tui/rendering.py:298-320` (BLOCK_RENDERERS registry)
**Issues**:
- BLOCK_RENDERERS dict maps block type names to render functions. LLM-specific renderers (MetadataBlock, TurnBudgetBlock, SystemLabelBlock, TrackedContentBlock, ToolUseBlock, ToolResultBlock, StreamToolUseBlock, StopReasonBlock, StreamInfoBlock) can be removed from the registry when the corresponding block types are deleted. This is clean.
- BLOCK_FILTER_KEY dict (lines 326-348) maps block types to filter keys. Same story -- remove LLM entries.
- Generic renderers (_render_separator, _render_header, _render_http_headers, _render_role, _render_text_content, _render_text_delta, _render_error, _render_proxy_error, _render_log, _render_newline) are all preserved.
- New renderers needed: _render_request_body, _render_response_body, _render_sse_event. These map to the new block types.
- The render_blocks() function (lines 383-427) has tool-use collapse logic (pending_tool_uses). DELETE that logic when ToolUseBlock is removed.
- render_turn_to_strips() is 100% generic. Keep.

### 11. Widget Factory (tui/widget_factory.py)
**Status**: ~20% LLM-specific
**Evidence**: ToolEconomicsPanel (lines 1149-1204), TimelinePanel (lines 1207-1260)
**Issues**:
- ConversationView class (lines 109-1073) is 95% generic. Only tool_turn navigation (`next_tool_turn`) references ToolUseBlock/ToolResultBlock/StreamToolUseBlock type names (line 944). This is a 3-line filter that can be removed.
- StatsPanel (lines 1075-1147) currently shows token counts. For generic proxy, should show request count, bytes transferred, status codes. Significant rewrite but same pattern.
- ToolEconomicsPanel, TimelinePanel: DELETE entirely.
- Factory functions at bottom: remove create_economics_panel(), create_timeline_panel().
- TurnData dataclass (lines 42-57) is 100% generic. Keep as-is.

### 12. Event Handlers (tui/event_handlers.py)
**Status**: ~30% LLM-specific
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/tui/event_handlers.py:156-174` (token tracking in handle_response_event)
**Issues**:
- handle_response_event() switches on Claude SSE event types (StreamInfoBlock, message_start, message_delta). For generic proxy, this handler would be simpler: just pass response blocks through.
- handle_response_done() refreshes economics and timeline panels (lines 220-223). Remove those callbacks.
- handle_request() uses format_request() which is the main Claude-specific formatter. Needs replacement with generic request formatting.
- The handler structure (event -> format -> widget update) is good and should be preserved.

### 13. Panel Renderers (tui/panel_renderers.py)
**Status**: ~90% DELETE
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/tui/panel_renderers.py` (149 lines)
**Issues**:
- render_stats_panel(): token-centric display. Rewrite for generic HTTP stats (request count, bytes, status codes).
- render_economics_panel(): 100% LLM. DELETE.
- render_timeline_panel(): 100% LLM. DELETE.

### 14. Hot Reload (hot_reload.py)
**Status**: GENERIC, needs name updates only
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/hot_reload.py:14-31`
**Issues**:
- _RELOAD_ORDER and _RELOAD_IF_CHANGED contain hardcoded "cc_dump.*" strings. Mechanical rename to "surview.*".
- Module list may need updating if modules are added/removed during retool (e.g., analysis.py deleted, new modules added).
- Infrastructure is 100% generic. No logic changes needed.

### 15. Sessions Module (sessions.py)
**Status**: 95% GENERIC
**Evidence**: `/Users/bmf/code/surview-py/src/cc_dump/sessions.py:19`
```python
return os.path.expanduser("~/.local/share/cc-dump/recordings")
```
**Issues**: Only coupling is the hardcoded path. Change to `~/.local/share/surview/recordings`.

### 16. Generic Infrastructure (100% keep)
- `router.py`: Completely generic event fan-out. Zero changes needed beyond package rename.
- `palette.py`: Color palette generator. Zero changes.
- `colors.py`: Tag color constants. Zero changes.
- `tui/protocols.py`: HotSwappableWidget protocol. Zero changes.
- `tui/custom_footer.py`: Rich markup footer. Zero changes.
- `tui/widgets.py`: Re-export shell. Needs to remove ToolEconomicsPanel/TimelinePanel exports.

## Test Files Assessment

### DELETE (100% LLM-specific, no salvageable patterns)
- `tests/test_analysis.py` (590 lines) -- tests TurnBudget, correlate_tools, ModelPricing
- `tests/test_token_counter.py` (80 lines) -- tests tiktoken wrapper
- `tests/test_store_token_counting.py` (219 lines) -- tests token counting in SQLite writer
- `tests/test_tool_economics.py` (347 lines) -- tests tool economics queries
- `tests/test_tool_economics_breakdown.py` (425 lines) -- tests model breakdown
- `tests/test_tool_rendering.py` (421 lines) -- tests tool use/result block rendering

### KEEP AND REWRITE (good test patterns, Claude-specific data)
- `tests/test_formatting.py` (1083 lines) -- tests block creation. Structure is good but all test data is Claude API payloads. Rewrite with generic HTTP payloads. ~30% salvageable.
- `tests/test_har_recorder.py` (637 lines) -- tests HAR recording. The HAR structure tests are good. SSE reconstruction tests are LLM-specific. ~40% salvageable.
- `tests/test_har_replayer.py` (681 lines) -- tests HAR replay. Validation tests are good, event synthesis tests are LLM-specific. ~30% salvageable.
- `tests/test_har_replay_integration.py` (383 lines) -- end-to-end replay. Good pattern but Claude-specific data. ~20% salvageable.
- `tests/test_e2e_record_replay.py` (561 lines) -- full pipeline test. Excellent pattern, all Claude data. ~20% salvageable.
- `tests/test_tui_integration.py` (838 lines) -- TUI integration with ptydriver. Good patterns for TUI testing. ~30% salvageable.
- `tests/test_visual_indicators.py` (516 lines) -- filter indicator rendering. Good patterns. ~40% salvageable.
- `tests/test_footer_rendering.py` (143 lines) -- footer display. ~50% salvageable.

### KEEP AS-IS (generic, minimal changes)
- `tests/test_router.py` (343 lines) -- 100% generic event router tests. Keep entirely, rename imports only.
- `tests/test_sessions.py` (295 lines) -- 95% generic session listing. Update path constants.
- `tests/test_schema.py` (113 lines) -- schema creation tests. Rewrite with new schema but keep pattern.
- `tests/test_hot_reload.py` (626 lines) -- hot reload tests. Update module names, keep patterns.
- `tests/test_scroll_nav.py` (781 lines) -- scroll/navigation tests. Keep patterns, update block types used in test data.
- `tests/test_widget_arch.py` (1018 lines) -- widget architecture tests. Keep patterns, update block type references.
- `tests/conftest.py` (176 lines) -- test fixtures. Update "cc-dump" references.

## Ambiguities Found
| Area | Question | How LLM Guessed | Impact |
|------|----------|-----------------|--------|
| Event schema | What event types does the generic proxy emit for non-SSE responses? | Not yet decided | HIGH -- Defines the contract between proxy and entire downstream pipeline |
| Body display | How should large response bodies be displayed? Truncated? Scrollable? | Not specified | MEDIUM -- Affects RequestBodyBlock/ResponseBodyBlock design |
| SSE parsing | Should generic SSE follow W3C spec (event: + data:) or also support API conventions ([DONE] sentinel)? | Current code is API-convention only | MEDIUM -- Determines what SSE streams can be debugged |
| Filter mapping | What does "body" filter show/hide? Request body? Response body? Both? | Not specified | MEDIUM -- Affects BLOCK_FILTER_KEY mapping |
| HAR format for non-JSON | How to record binary responses (images, protobuf) in HAR? | Not addressed | LOW for MVP -- HAR spec supports base64 content |
| DB schema | Should generic schema track request/response as separate rows or paired? | Not specified | MEDIUM -- Affects query patterns |
| Content tracking | Is the SHA256 content dedup system (TrackedContentBlock) being dropped entirely or repurposed? | Plan says "strip all LLM code" | LOW -- Can be added back later if needed for generic content |

## Phase Decomposition Analysis

The user asks whether "phases 3-7 can actually be done as a unit or need further decomposition."

**Phases from context**:
- Phase 1: Rename package (sprint plan exists)
- Phase 2: Delete LLM-specific code
- Phase 3-7: Rewrite core (IR, proxy, DB, HAR, TUI)
- Phase 8: tmux orchestration
- Phase 9: Tests and verification

**Assessment**: Phases 3-7 CANNOT be done as a single unit. Here is why:

The changes have a **strict dependency order** driven by the event schema:

1. **Proxy rewrite** (proxy.py) must come first. It defines the new event types that everything downstream consumes. Until this is done, nothing downstream can be rewritten because there's no contract to code against. This is the "single enforcer" -- proxy.py is the sole boundary between external HTTP and internal events.

2. **Formatting rewrite** (formatting.py) must come second. It defines the new FormattedBlock types (RequestBodyBlock, ResponseBodyBlock, SSEEventBlock) that rendering and event handlers consume. The new block types must match the new event schema from step 1.

3. **Rendering update** (tui/rendering.py) must come third. It needs new renderers for the new block types and removal of old renderers. It must happen after formatting because renderers consume block types.

4. **Event handlers + App rewrite** (tui/event_handlers.py, tui/app.py) can happen together because they consume both events and formatted blocks. They depend on steps 1 and 2.

5. **DB rewrite** (schema.py, store.py, db_queries.py) is somewhat independent but depends on the new event schema (step 1). Can be done in parallel with steps 3-4 if the event schema is locked.

6. **HAR rewrite** (har_recorder.py, har_replayer.py) depends on the new event schema. Can be done in parallel with steps 3-5.

**Recommended decomposition**:

```
Phase 1: Rename (existing sprint plan)
Phase 2: Delete dead code (analysis.py, token_counter.py, LLM-specific tests)
Phase 3: Proxy + Event Schema (proxy.py -- defines new contract)
Phase 4: Formatting IR (new block types, format_request/response functions)
Phase 5: Rendering + Event Handlers + App (consumes new blocks)
Phase 6: DB (new schema, store, queries -- can overlap with Phase 5)
Phase 7: HAR (record/replay with generic data -- can overlap with Phase 5)
Phase 8: tmux orchestration
Phase 9: Tests
```

Critical path: 1 -> 2 -> 3 -> 4 -> 5 -> 9

### Pre-existing Test Failure
**File**: `/Users/bmf/code/surview-py/tests/test_formatting.py:283`
**Test**: `test_format_response_event_message_start`
**Expected**: 1 block from message_start event
**Actual**: 2 blocks (RoleBlock + StreamInfoBlock)
**Analysis**: The branch `bmf_fix_missing_assistant_header` added a RoleBlock to message_start handling, but the test was not updated. This is on the current branch and is a pre-existing issue. Since formatting.py will be rewritten, this test failure is inconsequential -- it will be deleted in Phase 2.

## Architectural Concerns About New Generic HTTP Block Types

1. **RequestBodyBlock**: Needs to handle JSON (pretty-printed), form data, XML, raw text, and binary (hex dump or "[binary N bytes]" placeholder). The current TextContentBlock only handles plain text. A new block type that carries the content-type and raw body is needed to let the renderer choose display format.

2. **ResponseBodyBlock**: Same concerns as RequestBodyBlock, plus streaming. For SSE responses, the body arrives incrementally. The current TextDeltaBlock pattern (buffer + flush) can be reused here.

3. **SSEEventBlock**: Should carry the raw SSE event (event type + data). The renderer can decide whether to parse as JSON or display raw. This is simpler than the current approach which parses SSE into Claude-specific types.

4. **Filter model**: The plan says h(eaders), b(ody), s(se), f(ollow). This maps cleanly:
   - h: HeaderBlock, HttpHeadersBlock, SeparatorBlock
   - b: RequestBodyBlock, ResponseBodyBlock
   - s: SSEEventBlock, TextDeltaBlock
   - f: follow mode (not a content filter)

   This is a simplification from the current 8 content filters to 3. The rendering pipeline's existing BLOCK_FILTER_KEY mechanism handles this directly.

5. **No content tracking**: The plan drops TrackedContentBlock (SHA256 dedup for system prompts). This is correct for a generic proxy -- content dedup is LLM-specific. However, the DiffBlock type could still be useful for showing changes between repeated requests. Consider whether to keep DiffBlock or remove it.

## Recommendations
1. **Lock the event schema first** (Phase 3). Define the exact event tuple types the generic proxy will emit. This is the contract everything depends on. Proposed:
   - ("request_start", method, url, headers_dict) -- replaces request_headers
   - ("request_body", body_bytes, content_type) -- replaces request
   - ("response_start", status_code, headers_dict) -- replaces response_headers
   - ("response_body", body_bytes, content_type) -- new for non-streaming
   - ("sse_event", event_type, data_str) -- replaces response_event
   - ("response_done",) -- keep
   - ("error", code, reason) -- keep
   - ("proxy_error", error_str) -- keep
   - ("log", method, path, status) -- keep

2. **Add HTTP method handlers** to proxy.py: do_PUT, do_DELETE, do_PATCH, do_HEAD. Currently only POST and GET are handled.

3. **Remove the /v1/messages path filter** in proxy.py immediately. This is the single biggest blocker -- the proxy is blind to all non-Claude traffic.

4. **Preserve the blob storage infrastructure** (store.py:164-188, schema.py:39-44). Content-addressed blob storage is generic and useful for storing large request/response bodies.

5. **Delete analysis.py and token_counter.py early** (Phase 2). These have no dependents once formatting.py stops importing from analysis.py, and removing tiktoken from dependencies makes the install faster.

6. **Write a smoke test for Phase 3** immediately after proxy rewrite: start proxy, make a simple HTTP request through it, verify events are emitted for request and response. This validates the new contract before anything downstream is built.

7. **Keep test_router.py as a regression anchor**. It tests the generic event fan-out which should not change.

## Verdict
- [x] CONTINUE - Issues clear, implementer can fix
- [ ] PAUSE - Ambiguities need clarification

The plan is sound and the codebase is well-structured for this retool. The main risk is attempting Phases 3-7 as a single unit -- they must be ordered with the proxy/event schema first. The ambiguities listed above (event schema, body display, filter mapping) are design decisions that can be resolved during implementation as long as the proxy event schema is decided first.

The existing sprint plan (rename-package) is correct as Phase 1 and ready for implementation.
