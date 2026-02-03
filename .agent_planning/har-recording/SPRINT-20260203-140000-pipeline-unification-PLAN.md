# Sprint: pipeline-unification - Pipeline Unification and SQLite Deprecation Path
Generated: 2026-02-03T14:00:00
Confidence: HIGH: 1, MEDIUM: 2, LOW: 1
Status: RESEARCH REQUIRED
Source: EVALUATION-20260203-120000.md

## Sprint Goal
Evaluate whether JSONL recordings can replace SQLite as the primary persistence layer, and implement any remaining integration to make recording/replay a first-class citizen.

## Scope
**Deliverables:**
- Analysis: JSONL vs SQLite role definition (which is source of truth for what?)
- Session listing/management for replay files
- Documentation updates (ARCHITECTURE.md, CLAUDE.md)
- End-to-end integration test: live capture -> record -> replay -> verify identical output

## Work Items

### P1 - Persistence Role Clarification (MEDIUM confidence)

**Dependencies**: Sprint 1 + Sprint 2 complete
**Spec Reference**: ARCHITECTURE.md "Database Layer", PROJECT_SPEC.md "Database as source of truth for aggregates"
**Status Reference**: EVALUATION-20260203-120000.md "SQLite Persistence" and "Architectural Gap"

#### Description
With JSONL recording in place, the system has two persistence mechanisms:
1. **JSONL recording**: Verbatim event stream (complete, ordered, replayable)
2. **SQLite database**: Aggregated turns with analytics (tokens, tools, search)

The ticket says "Loading from serialization must become the DEFAULT/ONLY code path." This means JSONL is the canonical raw data source. But SQLite still serves a valuable role for analytics queries (token counts, tool stats, FTS search) that cannot efficiently run on JSONL.

This work item defines the authoritative role of each:
- **JSONL**: Source of truth for raw event data. Used for replay/restore.
- **SQLite**: Derived index. Rebuilt from JSONL on demand. Used for queries/analytics.

#### Acceptance Criteria
- [ ] Document in ARCHITECTURE.md: JSONL = source of truth for events, SQLite = derived index
- [ ] Verify: SQLite can be deleted and rebuilt by replaying JSONL through the pipeline
- [ ] Verify: no data in SQLite that cannot be reconstructed from JSONL

#### Unknowns to Resolve
1. Is the current SQLite schema sufficient when populated via replay? Research: replay a session, compare SQLite contents to live-captured version
2. Should SQLite be rebuilt on startup from JSONL, or kept as a cache? Research: measure rebuild time for typical sessions (100-500 turns)

#### Exit Criteria (to reach HIGH)
- [ ] Role of each persistence layer documented and agreed
- [ ] Rebuild path verified (JSONL -> SQLite produces same data)

---

### P2 - Session Management CLI (MEDIUM confidence)

**Dependencies**: Sprint 1 recording, Sprint 2 replay
**Spec Reference**: PROJECT_SPEC.md "Zero Configuration"
**Status Reference**: N/A (new capability)

#### Description
Users need to discover and manage recorded sessions. Implement:
- `cc-dump --list` to show available recordings (from default recordings directory)
- `cc-dump --replay latest` shortcut for most recent recording
- Display: session date, duration, event count, file size

#### Acceptance Criteria
- [ ] `--list` shows available recordings with metadata
- [ ] `--replay latest` replays most recent recording
- [ ] Output format: date, event count, file size per recording

#### Unknowns to Resolve
1. Should session management be a subcommand (`cc-dump sessions list`) or flags? Research: existing CLI patterns in the codebase
2. Should old recordings be auto-pruned? Research: what storage growth looks like for typical usage

#### Exit Criteria (to reach HIGH)
- [ ] CLI interface design decided (subcommand vs. flags)
- [ ] Auto-pruning policy decided (if any)

---

### P2 - End-to-End Integration Test (HIGH confidence)

**Dependencies**: Sprint 1 + Sprint 2 complete
**Spec Reference**: CLAUDE.md "Tests assert behavior, not structure"
**Status Reference**: EVALUATION-20260203-120000.md "Test coverage needed"

#### Description
Write an integration test that:
1. Creates a mock event stream (representative sequence of all event types)
2. Records it to JSONL via RecordingSubscriber
3. Replays it via EventReplayer
4. Processes through formatting pipeline
5. Verifies FormattedBlock output is identical between direct processing and replay processing

This is the definitive test of "zero divergence."

#### Acceptance Criteria
- [ ] Test creates realistic event sequence covering all 8 event types
- [ ] Records to temp file, replays from temp file
- [ ] FormattedBlock lists compared for equality
- [ ] Content tracking state compared for equality
- [ ] Test passes reliably (no timing-dependent flakiness)

#### Technical Notes
- Use `speed=0` (instant) for the integration test to avoid timing issues
- Compare at the FormattedBlock level, not the rendered Strip level (blocks are the contract)
- Can run formatting synchronously without TUI for comparison

---

### P3 - Architecture Documentation Update (LOW confidence)

**Dependencies**: All above work items
**Spec Reference**: ARCHITECTURE.md, CLAUDE.md
**Status Reference**: N/A

#### Description
Update ARCHITECTURE.md to reflect the new event recording/replay architecture. Update CLAUDE.md with new CLI flags and module classification.

This is LOW confidence because the exact content depends on decisions made in the MEDIUM confidence items above.

#### Acceptance Criteria
- [ ] ARCHITECTURE.md updated with recording/replay data flow diagram
- [ ] ARCHITECTURE.md documents JSONL format specification
- [ ] CLAUDE.md updated with --replay, --record flags
- [ ] recorder.py and replayer.py classified as stable modules in hot-reload table

#### Unknowns to Resolve
1. Final architecture depends on persistence role clarification outcome
2. CLI flags may change based on session management decisions

#### Exit Criteria (to reach MEDIUM)
- [ ] Sprint 1 and Sprint 2 fully implemented
- [ ] Persistence role clarification complete
- [ ] Session management CLI design decided

## Dependencies
- Sprint 1 (event-recording) MUST be complete
- Sprint 2 (event-replay) MUST be complete
- This sprint is intentionally last because it depends on learnings from implementation

## Risks
- **Medium risk**: JSONL files for long sessions could be large (100MB+). Mitigation: consider gzip compression (.jsonl.gz) for storage, decompress on replay.
- **Medium risk**: SQLite rebuild from JSONL may be slow for large sessions. Mitigation: keep SQLite as persistent cache, only rebuild when missing.
- **Low risk**: Session management scope could expand. Mitigation: start minimal (list + latest), expand based on user feedback.
