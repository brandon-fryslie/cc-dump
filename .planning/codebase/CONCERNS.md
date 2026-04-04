# CONCERNS.md — cc-dump Technical Debt, Known Issues, and Risk Areas

**Date:** 2026-04-03
**Scope:** Architecture review + code audit + known issues from tracking
**Status:** Active codebase with ongoing work

---

## CRITICAL ISSUES

### 1. Unverified Translation Path (Copilot Integration)
**Status:** In-progress work
**Location:** `src/cc_dump/pipeline/copilot_translate.py`, `src/cc_dump/pipeline/proxy.py`
**Risk Level:** **HIGH** — Incomplete end-to-end verification

**What:**
- Anthropic↔Copilot API translation layer is code-complete but untested against live APIs
- Translation module handles bidirectional SSE conversion for OpenAI Responses API (not Chat Completions)
- Several edge cases remain unhandled:
  - **Tool use stop_reason:** Currently hardcoded to `"end_turn"` — should be `"tool_use"` when Copilot returns only function calls
  - **Parallel tool calls:** Can return 3-7 tool calls per response; translation logic present but unverified
  - **Content block ordering:** When reasoning + function_calls without text, verify Claude Code handles tool_use without preceding text
  - **Error handling:** Error responses from Copilot not yet translated

**Next Action:** End-to-end verification with mock or real Copilot API using reference HAR files (`reference/copilot-cli-har_04-03-2026-15-49-41.har`, 142MB)

**Files:**
- `src/cc_dump/pipeline/copilot_translate.py`
- `src/cc_dump/pipeline/proxy.py` (_REQUEST_TRANSLATORS, _HEADER_BUILDERS, _STREAM_HANDLERS dispatch tables)
- `src/cc_dump/cli.py` (_UPSTREAM_PRESETS)

---

### 2. API Key Exposure in Recorded HAR Files
**Status:** Design accepted with risks documented
**Location:** `src/cc_dump/pipeline/har_recorder.py`, `src/cc_dump/pipeline/proxy.py`
**Risk Level:** **CRITICAL** — Proxy records complete API traffic including auth headers to disk

**What:**
- HAR files stored at `~/.local/share/cc-dump/recordings/<session>/<provider>/recording-*.har` contain complete HTTP request/response pairs
- Request headers **exclude** Authorization/API-Key headers via `_EXCLUDED_HEADERS` in `proxy.py` (`_safe_headers()`)
- **But:** Request body contains potentially sensitive data (model names, conversation content, system prompts)
- Response body contains complete API responses with all user conversation history
- **Risk:** If recording directory is world-readable or backup is compromised, API tokens and conversations are exposed

**Mitigation Status:**
- ✅ Authorization header excluded from events + HAR
- ⚠️ HAR files not encrypted at rest
- ⚠️ Directory permissions not enforced (user responsibility)
- ⚠️ No automatic redaction of sensitive fields in request/response bodies
- ⚠️ No warning to user at startup about recording implications

**Recommended:**
- Document security implications in README/CLI help
- Add `--no-record` to disable recording for sensitive sessions
- Consider adding an opt-in redaction mode for recording

**Files:**
- `src/cc_dump/pipeline/har_recorder.py:44-61` (header filtering)
- `src/cc_dump/pipeline/proxy.py:44-62` (_EXCLUDED_HEADERS, _safe_headers)

---

### 3. Copilot Token File Permissions
**Status:** Implicit assumption
**Location:** `src/cc_dump/pipeline/copilot_translate.py`
**Risk Level:** **MEDIUM** — Reads auth token from file system

**What:**
- Token read from `~/.local/share/copilot-api/github_token` (GitHub OAuth token)
- No validation that file is readable only by owner
- Token passed in memory and sent to Copilot API with minimal hardening

**Mitigation Status:**
- ⚠️ No permission check on token file (assumes user config correct)
- ⚠️ No protection against accidental stdout/logging of token

**Recommended:**
- Add defensive check: `os.stat(path).st_mode & 0o077 == 0` (warn if readable by group/other)
- Consider loading from environment variable fallback (`GITHUB_TOKEN`)

**Files:**
- `src/cc_dump/pipeline/copilot_translate.py:48-62` (read_copilot_token)

---

## MAJOR ARCHITECTURE CONCERNS

### 4. God Modules Creating High Coupling
**Status:** Documented in COMPLEXITY_AUDIT_2026-03-10.md
**Risk Level:** **HIGH** — Blast radius for bug fixes, feature additions

**What:**
- `src/cc_dump/tui/rendering_impl.py` — 4,212 LOC, mixes theme runtime, block renderers, search highlighting, truncation policy, recursive render
- `src/cc_dump/tui/widget_factory.py` — 2,552 LOC, combines virtual renderer internals with panel classes/factories and hot-reload state transfer
- `src/cc_dump/core/formatting_impl.py` — 1,577 LOC, combines IR definitions, provider-specific formatting, parsing, presentation heuristics
- `src/cc_dump/pipeline/proxy.py` — 757 LOC, carries multiple orthogonal modes (forward/reverse, CONNECT, stream/non-stream, translation dispatch)

**Impact:**
- Changes to any subsystem force edits across multiple god modules
- Test surface area is very large; isolation tests difficult
- Rendering changes have high regression risk (affects all content visibility)
- Proxy changes risk breaking all provider families

**Recommended:** See COMPLEXITY_AUDIT Phase 3 for decomposition plan

**Files:**
- `src/cc_dump/tui/rendering_impl.py` (4,212 lines)
- `src/cc_dump/tui/widget_factory.py` (2,552 lines)
- `src/cc_dump/core/formatting_impl.py` (1,577 lines)
- `src/cc_dump/pipeline/proxy.py` (757 lines)

---

### 5. State Duplication Across Runtime Layers
**Status:** Known, partially addressed in ongoing refactors
**Risk Level:** **HIGH** — Divergence can cause silent bugs

**What:**
- Runtime state has overlapping representations: `state` dict, `provider_states`, `store_context`, private app internals (`_store_context`, `_error_log`)
- CLI touches app internals directly (`app._app_log`, `app._error_log`) instead of through public API
- Side-channel result state mirrored to two key families (`sc:*` and `workbench:*`) — no single source of truth
- TmuxController has dual launch-env paths (`_launch_env` and legacy `_port` fallback)

**Impact:**
- State changes silently propagate (or fail to) through multiple representations
- Hard to reason about which representation is authoritative
- Refactoring risk very high

**Recommended:**
- Consolidate to single runtime context
- Make app API public instead of reaching into internals
- Remove legacy `_port` fallback path

**Files:**
- `src/cc_dump/cli.py:529-677` (state duplication, internal reach-ins)
- `src/cc_dump/tui/side_channel_controller.py:254-259` (state mirroring)
- `src/cc_dump/app/tmux_controller.py:129-419` (dual env paths)

---

### 6. Search Navigation Intentionally Stubbed
**Status:** Known incomplete refactoring
**Risk Level:** **MEDIUM** — UX feature broken by design

**What:**
- Search keyboard navigation deliberately left as TODO no-ops: `navigate_next()`, `navigate_prev()`, `navigate_to_current()`
- UI allows entering search but navigation doesn't work
- User can search but can't move between results without clicking

**Impact:**
- Keyboard-first navigation workflow is broken for search
- Risk of silent complaints if users try this path

**Recommended:**
- Either complete implementation or remove search navigation from keymap
- Decide on priority with product owner

**Files:**
- `src/cc_dump/tui/search_controller.py:389-414` (navigate_* methods stubbed)

---

### 7. Dead/Legacy Panel Infrastructure
**Status:** Vestigial from previous design
**Risk Level:** **MEDIUM** — Dead code paths create confusion, regress risk

**What:**
- Legacy panel names `economics` and `timeline` are wired into:
  - Action handlers (`action_handlers.py:527`)
  - Hot-reload logic (`hot_reload_controller.py:609`)
  - App helpers (`app.py:624`)
- But panel registry only defines `session` and `stats` panels
- No error when unknown panel is requested; falls through to unhandled code path

**Impact:**
- Dead code increases maintenance burden
- Inconsistency between registry and wired names creates confusion
- Refactoring panel lifecycle breaks silently

**Recommended:**
- Delete legacy panel branches from all three locations
- OR reintroduce them through registry (if intended for future)

**Files:**
- `src/cc_dump/tui/panel_registry.py:22` (registry definition)
- `src/cc_dump/tui/action_handlers.py:527` (legacy wiring)
- `src/cc_dump/tui/app.py:624` (legacy helpers)
- `src/cc_dump/tui/hot_reload_controller.py:609` (legacy hot-reload)

---

### 8. Provider Inference Silently Falls Back to OpenAI
**Status:** Incomplete error handling
**Risk Level:** **MEDIUM** — Unrecognized providers silently degrade

**What:**
- When provider family is unknown, `proxy.py` silently assumes OpenAI extraction/assembly
- No warning to user that provider is unrecognized
- HAR replayer does same silent fallback

**Impact:**
- New provider support doesn't fail loudly
- Hard to debug why traffic from unknown provider is corrupted
- Silent degradation violates [LAW:no-silent-fallback-data-sources]

**Recommended:**
- Raise error on unknown provider instead of silent fallback
- Log warning if fallback is truly intentional

**Files:**
- `src/cc_dump/pipeline/proxy.py:252, 622` (silent OpenAI fallback)

---

### 9. Provider Inference Logic Duplicated
**Status:** Known duplication
**Risk Level:** **MEDIUM** — Semantic drift between paths

**What:**
- Provider inference implemented in three places:
  - `src/cc_dump/io/sessions.py:46, 90`
  - `src/cc_dump/pipeline/har_replayer.py:125, 138`
  - Implicit in provider registry lookup
- No canonical location; divergence possible

**Impact:**
- Session list and HAR replay can show different providers for same content
- Adding new provider requires edits in multiple places

**Recommended:**
- Centralize provider inference in `providers.py`
- Call canonical function from both sessions and replayer

**Files:**
- `src/cc_dump/io/sessions.py:46-90` (inference logic)
- `src/cc_dump/pipeline/har_replayer.py:125-138` (duplicate inference)

---

### 10. Event Envelope Fields Manually Threaded
**Status:** Parameter threading anti-pattern
**Risk Level:** **MEDIUM** — Fragile, error-prone

**What:**
- Event envelope fields (`request_id`, `seq`, `recv_ns`, `provider`) are manually threaded through proxy and replay paths
- No canonical event constructor; values scattered across multiple call sites
- Easy to miss a field or mis-thread it

**Impact:**
- Events can be missing metadata
- Inconsistent between live and replay modes (cosmetic but confusing)
- Adding new event fields requires edits in many places

**Recommended:**
- Introduce canonical event envelope constructor
- Use it consistently in both proxy.py and har_replayer.py

**Files:**
- `src/cc_dump/pipeline/proxy.py:420, 524, 551, 630` (manual envelope construction)
- `src/cc_dump/pipeline/har_replayer.py:186` (replay envelope construction)

---

## PERFORMANCE CONCERNS

### 11. Virtual Rendering Cache Strategy Unclear
**Status:** Implemented but undocumented
**Risk Level:** **MEDIUM** — Cache invalidation hazard

**What:**
- `ConversationView` uses `LRUCache` (Textual's cache) for pre-rendered strips
- Cache invalidation rules scattered across `widget_factory.py`
- Multiple version counters: `_strip_version`, `_last_render_key`, `_filter_revision`, `_stream_last_delta_version`
- Cache-busting logic complex; easy to introduce stale renders

**Impact:**
- If cache not invalidated on theme/filter/search changes, old content displays
- If cache too aggressive, renders redundant
- Performance optimization could regress

**Recommended:**
- Document cache invalidation contract clearly
- Add assertions/logging to detect stale cache hits during testing
- Consider centralizing version tracking

**Files:**
- `src/cc_dump/tui/widget_factory.py:96-98` (version counter fields)
- `src/cc_dump/tui/rendering_impl.py` (rendering logic that must invalidate)

---

### 12. No Token Formatting (Placeholder Only)
**Status:** Incomplete feature
**Risk Level:** **LOW** — Cosmetic, diagnostic impact

**What:**
- `src/cc_dump/core/analysis.py:27` — `fmt_tokens()` always returns `"x"` (placeholder)
- Token counts calculated correctly but never displayed in UI with real formatting
- Analytics/budget panels show `x tokens` instead of actual counts

**Impact:**
- User can't see token breakdowns in UI
- Budget tracking is opaque
- Diagnostics are unhelpful

**Recommended:**
- Implement real token formatting (e.g., `"1,234 tokens"` or `"1.2K"`)
- Add tests covering panel/dump rendering with real numbers

**Files:**
- `src/cc_dump/core/analysis.py:27` (fmt_tokens placeholder)

---

### 13. Complex Streaming Logic with Multiple Delta Buffers
**Status:** Implemented, likely fragile
**Risk Level:** **MEDIUM** — Streaming edge cases

**What:**
- Streaming turns accumulate `TextDeltaBlock` fragments in `_text_delta_buffer`
- Boundary between "stable" and "streaming" strips tracked with `_stable_strip_count`
- Multiple render cycles possible before finalization
- Preview rendering of incomplete streams has separate width tracking

**Impact:**
- Streaming preview might diverge from finalized rendering
- Edge case: very large responses might hit performance cliff
- Hard to test all streaming sequences

**Recommended:**
- Add performance regression tests for large/long-streaming responses
- Document streaming contract (what happens if client disconnects mid-stream?)

**Files:**
- `src/cc_dump/tui/widget_factory.py:89-95` (streaming fields)
- `src/cc_dump/tui/event_handlers.py` (streaming accumulation logic)

---

## SECURITY CONCERNS

### 14. HAR Files World-Writable Directory Risk
**Status:** Implicit assumption
**Risk Level:** **MEDIUM** — Directory permission escalation

**What:**
- HAR files created at `~/.local/share/cc-dump/recordings/` with default umask
- If `~/.local/share` is writable by group/other, anyone can modify recorded traffic
- No file permission enforcement in code

**Impact:**
- Recorded conversations could be modified post-recording
- Attacker could inject fake HAR entries

**Recommended:**
- Create directory with restricted permissions (0o700)
- Set file permissions to 0o600 (owner-only read/write)

**Files:**
- `src/cc_dump/pipeline/har_recorder.py:180-196` (file creation)

---

### 15. No Input Validation on HAR Replay
**Status:** Partial validation
**Risk Level:** **MEDIUM** — Malformed input handling

**What:**
- HAR replay validates JSON structure but doesn't validate:
  - Request body schema (is it a valid Claude API request?)
  - Response body schema (is it a valid Claude API response?)
  - Suspicious field values (e.g., negative token counts)
- Invalid data is silently skipped with warning

**Impact:**
- Corrupted HAR files could crash formatters downstream
- Doesn't fail loudly on invalid input

**Recommended:**
- Add schema validation using pydantic before replaying
- Raise error on invalid schemas (not silent skip)

**Files:**
- `src/cc_dump/pipeline/har_replayer.py:24-150` (load_har function)

---

### 16. No Rate Limiting in Proxy
**Status:** Unimplemented
**Risk Level:** **LOW** — Not a security issue for local proxy, but noted

**What:**
- Proxy forwards all requests to upstream without rate limiting
- Malicious client could spam requests to exhaust Claude API quota

**Impact:**
- Potentially high API cost if client misbehaves
- Not typically a risk (local proxy, user controls client)

**Recommended:**
- Low priority, but could add optional rate limiting if abuse suspected

---

## DATA INTEGRITY CONCERNS

### 17. Side-Channel Budget Accounting Underpowered
**Status:** Known gap, documented in COMPLEXITY_AUDIT
**Risk Level:** **MEDIUM** — Budget enforcement unreliable

**What:**
- Side-channel token accounting is sparse; token fields scattered
- Budget caps depend on token counts that may not be available
- No single place where budget decisions are enforced

**Impact:**
- Budget guardrails may not prevent overspend
- User can't trust budget UI to reflect true consumption

**Recommended:**
- Centralize token tracking and budget enforcement
- Add invariant checks at budget decision points

**Files:**
- `src/cc_dump/ai/data_dispatcher.py:147` (sparse accounting)
- `src/cc_dump/ai/side_channel_analytics.py:26` (analytics structure)
- `src/cc_dump/ai/side_channel.py:305` (token field access)

---

### 18. Multiple Token Estimation Implementations
**Status:** Known duplication
**Risk Level:** **MEDIUM** — Semantic drift

**What:**
- Token estimation/scope logic duplicated across:
  - `src/cc_dump/core/analysis.py:16`
  - `src/cc_dump/ai/conversation_qa.py:201, 83`
  - `src/cc_dump/ai/data_dispatcher.py:543`
- Each path could calculate differently

**Impact:**
- Side-channel analytics and main analytics show different token counts
- User can't trust consistency of reported token usage

**Recommended:**
- Consolidate token estimation to single canonical function
- Call from all paths

**Files:**
- `src/cc_dump/core/analysis.py` (canonical)
- `src/cc_dump/ai/conversation_qa.py` (duplicate)
- `src/cc_dump/ai/data_dispatcher.py` (duplicate)

---

### 19. Marker Classification Ownership Split
**Status:** Scattered concern
**Risk Level:** **LOW** — Refactoring friction

**What:**
- Marker type classification logic split between:
  - `src/cc_dump/core/formatting_impl.py:43` (main classifier)
  - `src/cc_dump/core/special_content.py:37` (secondary classifier)
- No clear authority

**Impact:**
- Adding new marker types requires edits in multiple places
- Easy to forget a location

**Recommended:**
- Consolidate marker classification to single module

**Files:**
- `src/cc_dump/core/formatting_impl.py:43`
- `src/cc_dump/core/special_content.py:37`

---

## TESTING CONCERNS

### 20. Incomplete Hot-Reload Test Coverage
**Status:** Tests present but edge cases not covered
**Risk Level:** **MEDIUM** — Reload bugs may surface under production load

**What:**
- Hot-reload tests cover basic reload scenarios
- But don't test:
  - Large-scale state transfer (1000+ turns)
  - Reload during active streaming
  - Reload with error conditions in progress
  - Reload with multiple concurrent clients (reverse proxy mode)

**Impact:**
- Reload under production load might corrupt state
- Widget state transfer could lose data

**Recommended:**
- Add stress tests for reload with many turns
- Add reload-during-streaming test
- Add reload-with-errors test

**Files:**
- `tests/test_hot_reload.py` (hot-reload tests)

---

### 21. No Integration Tests for Provider Translation
**Status:** Unit tests exist, integration tests missing
**Risk Level:** **MEDIUM** — Live API integration untested

**What:**
- Translation module has unit tests but not end-to-end tests
- No mocked Copilot API tests
- No tests with real Claude Code client

**Impact:**
- Translation bugs only discovered in production
- Hard to verify against actual API behavior

**Recommended:**
- Add mocked Copilot API server with canned responses
- Add integration test with simulated Claude Code client
- Use reference HAR files for known-good responses

**Files:**
- `tests/test_copilot_translate.py` (unit tests only)

---

## DOCUMENTATION CONCERNS

### 22. Implicit Assumptions About File Permissions
**Status:** Not documented
**Risk Level:** **LOW** — Surprise for security-conscious users

**What:**
- Code assumes `~/.local/share/copilot-api/github_token` is owned by user with 0o600
- No enforcement or check
- Not documented in README

**Impact:**
- User might unknowingly store token with wrong permissions
- No warning if file is world-readable

**Recommended:**
- Add permission check with warning in code
- Document expected file permissions in README

---

### 23. Hot-Reload Architecture Partially Documented
**Status:** HOT_RELOAD_ARCHITECTURE.md exists but incomplete
**Risk Level:** **LOW** — Developer friction

**What:**
- Module reloading documented well
- But widget hot-swap state transfer protocol could be clearer
- Widget state examples minimal

**Impact:**
- New developers struggle adding new widgets
- Easy to miss `get_state()`/`restore_state()` protocol

**Recommended:**
- Add more widget state examples
- Document how to debug state loss issues

**Files:**
- `docs/HOT_RELOAD_ARCHITECTURE.md` (documentation)

---

### 24. No Runbook for Recovery from Incomplete Proxy Shutdown
**Status:** Unhandled edge case
**Risk Level:** **LOW** — Recovery procedure unclear

**What:**
- If proxy crashes or is force-killed, port might remain bound
- No documented procedure to recover

**Impact:**
- User has to manually find and kill rogue process
- Unclear how long OS holds port

**Recommended:**
- Document port recovery procedure in README
- Consider adding `--port-recovery` command to clean up

---

## DEPENDENCY CONCERNS

### 25. Heavy Textual Framework Dependency
**Status:** Design choice, acceptable but noted
**Risk Level:** **LOW** — Framework risk

**What:**
- TUI is deeply integrated with Textual (ScrollView, reactive, Line API)
- Textual is actively developed by Textualize but smaller ecosystem than Qt/PyQt
- Bug in Textual could block cc-dump releases

**Impact:**
- Textual upgrades could require TUI rewrites
- Framework bugs hard to work around

**Recommended:**
- Monitor Textual releases for breaking changes
- Consider vendoring critical Textual APIs if needed

**Files:**
- `src/cc_dump/tui/widget_factory.py` (Textual integration)
- `src/cc_dump/tui/rendering_impl.py` (Textual rendering)

---

### 26. SnarfX as Separate Git Repository
**Status:** Architectural decision, working but unusual
**Risk Level:** **LOW** — Operational friction

**What:**
- `snarfx/` is separate git repo inside cc-dump working directory
- Git commands must use `git -C snarfx` instead of normal `git add`
- Easy to accidentally commit snarfx to cc-dump repo

**Impact:**
- Requires disciplined workflow
- CI/CD might commit snarfx accidentally

**Recommended:**
- Add pre-commit hook to prevent snarfx files in cc-dump commits
- Document in onboarding guide

**Files:**
- `snarfx/` (separate repo)
- `src/cc_dump/app/view_store.py` (uses snarfx)

---

## MONITORING & OBSERVABILITY CONCERNS

### 27. Limited Instrumentation for Proxy Traffic
**Status:** Logging present but limited metrics
**Risk Level:** **LOW** — Diagnostic friction

**What:**
- Proxy logs events but doesn't track:
  - Request latency distribution
  - Error rates by provider
  - Dropped/corrupted event counts
  - Streaming stall detection

**Impact:**
- Hard to diagnose proxy performance issues
- No visibility into error patterns

**Recommended:**
- Add metrics collection (in-memory only, no external deps)
- Expose metrics in debug panel

---

### 28. No Watchdog for Hung Streaming
**Status:** Unimplemented
**Risk Level:** **LOW** — Edge case handling

**What:**
- If client or server hangs mid-stream, proxy waits indefinitely
- No timeout for stuck streams
- User sees frozen turn indefinitely

**Impact:**
- UI frozen until client/server recovers
- No way to cancel hung turn

**Recommended:**
- Add configurable stream timeout (default 5min)
- Close hung streams and emit error event

---

## DEPLOYMENT & OPS CONCERNS

### 29. HAR Recording Default Always On
**Status:** Design choice, but has side effects
**Risk Level:** **LOW** — Privacy surprise

**What:**
- HAR recording enabled by default; no opt-in required
- User might not realize conversations are being recorded to disk
- `--no-record` flag exists but obscure

**Impact:**
- Privacy-conscious users surprised by recording
- Conversations accumulate on disk

**Recommended:**
- Consider opt-in recording by default (safer, users can enable if desired)
- OR more prominent warning at startup

**Files:**
- `src/cc_dump/cli.py` (recording setup)

---

### 30. No Automatic HAR Cleanup Policy
**Status:** Unimplemented
**Risk Level:** **MEDIUM** — Disk space creep

**What:**
- HAR files accumulate indefinitely in `~/.local/share/cc-dump/recordings/`
- No automatic deletion, rotation, or archival
- User could run out of disk space silently

**Impact:**
- Disk space creep over time
- Old recordings never cleaned up

**Recommended:**
- Implement retention policy (e.g., keep last 30 days, or max 1GB)
- Add `--cleanup` command to manage recordings

**Files:**
- `src/cc_dump/io/sessions.py` (session listing, could manage cleanup)

---

## SUMMARY TABLE

| Issue | Risk | Category | Mitigation |
|-------|------|----------|-----------|
| Copilot translation untested E2E | HIGH | Correctness | E2E testing |
| API key exposure in HAR | CRITICAL | Security | Encryption, warnings |
| Copilot token file permissions | MEDIUM | Security | Permission check |
| God modules coupling | HIGH | Architecture | Decomposition |
| State duplication | HIGH | Architecture | Consolidation |
| Search nav broken | MEDIUM | UX | Feature completion |
| Dead panel code | MEDIUM | Maintenance | Cleanup |
| Provider inference fallback | MEDIUM | Reliability | Error on unknown |
| Provider duplication | MEDIUM | Maintenance | Centralization |
| Event envelope threading | MEDIUM | Maintainability | Constructor function |
| Cache invalidation unclear | MEDIUM | Performance | Documentation |
| Token formatting placeholder | LOW | UX | Feature completion |
| Streaming edge cases | MEDIUM | Reliability | Stress testing |
| HAR file permissions | MEDIUM | Security | Permission enforcement |
| No HAR schema validation | MEDIUM | Security | Schema validation |
| Side-channel accounting | MEDIUM | Data integrity | Centralization |
| Token duplication | MEDIUM | Data integrity | Consolidation |
| Marker classification split | LOW | Maintenance | Consolidation |
| Hot-reload coverage gaps | MEDIUM | Testing | Stress tests |
| Provider translation tests | MEDIUM | Testing | Integration tests |
| File permission docs | LOW | Documentation | README update |
| Hot-reload docs incomplete | LOW | Documentation | More examples |
| Proxy shutdown recovery | LOW | Documentation | Runbook |
| Textual dependency risk | LOW | Dependencies | Framework monitoring |
| SnarfX git workflow friction | LOW | Workflow | Pre-commit hook |
| Limited proxy instrumentation | LOW | Observability | Metrics collection |
| No streaming watchdog | LOW | Reliability | Timeout implementation |
| HAR recording default | LOW | Privacy | Consider opt-in |
| HAR cleanup missing | MEDIUM | Operations | Retention policy |

---

## RECOMMENDED PRIORITY

### Phase 1: Immediate (Blocking)
1. **API Key Exposure (Issue #2)** — Add security warnings and `--no-record` default guidance
2. **Copilot E2E Verification (Issue #1)** — Complete end-to-end testing before shipping
3. **Dead Panel Code (Issue #7)** — Remove vestigial paths

### Phase 2: Soon (Stability)
4. **God Module Decomposition (Issue #4)** — Start with rendering_impl split
5. **State Consolidation (Issue #5)** — Single runtime context
6. **Event Envelope Constructor (Issue #10)** — Centralize event building

### Phase 3: Medium Term (Quality)
7. **Token Formatting (Issue #12)** — Implement real display
8. **Search Navigation (Issue #6)** — Complete or remove
9. **HAR Cleanup Policy (Issue #30)** — Implement retention

### Phase 4: Nice to Have (Polish)
10. **Streaming Stress Tests (Issue #13)** — Large response handling
11. **Proxy Instrumentation (Issue #27)** — Metrics collection
12. **Documentation Updates (Issues #22-24)** — Runbooks and examples
