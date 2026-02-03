# Definition of Done: pipeline-unification
Generated: 2026-02-03T14:00:00
Status: RESEARCH REQUIRED
Plan: SPRINT-20260203-140000-pipeline-unification-PLAN.md

## Acceptance Criteria

### Persistence Role Clarification
- [ ] ARCHITECTURE.md documents JSONL = source of truth, SQLite = derived
- [ ] SQLite deletable and rebuildable from JSONL verified
- [ ] No data in SQLite that cannot be reconstructed from JSONL

### Session Management CLI
- [ ] `--list` shows available recordings
- [ ] `--replay latest` replays most recent
- [ ] Per-recording metadata displayed

### End-to-End Integration Test
- [ ] Realistic event sequence covering all 8 types
- [ ] Record -> replay -> compare FormattedBlocks
- [ ] Content tracking state identical
- [ ] No timing-dependent flakiness

### Architecture Documentation
- [ ] ARCHITECTURE.md updated with recording/replay flow
- [ ] JSONL format documented
- [ ] CLAUDE.md updated with new CLI flags
- [ ] Module classification updated

## Exit Criteria (for MEDIUM/LOW items)
- [ ] Persistence role clarification decided and documented
- [ ] CLI interface design (subcommand vs. flags) decided
- [ ] Auto-pruning policy decided
- [ ] All Sprint 1 + Sprint 2 work complete
