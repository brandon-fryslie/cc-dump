# Definition of Done: event-replay
Generated: 2026-02-03T13:00:00
Status: PARTIALLY READY
Plan: SPRINT-20260203-130000-event-replay-PLAN.md

## Acceptance Criteria

### Event Replayer Module
- [ ] `EventReplayer(path, queue, speed)` validates file and reads header
- [ ] `start()` begins replay in background daemon thread
- [ ] Events pushed to queue in original order
- [ ] Speed modes: instant (0), realtime (1.0), multiplied (Nx)
- [ ] Completion signaled when all events replayed

### CLI Replay Mode
- [ ] `--replay <path>` accepted by argparse
- [ ] No HTTP server started in replay mode
- [ ] TUI displays replayed events identically to live
- [ ] SQLite populated from replayed events
- [ ] `--replay` + `--record` combination works
- [ ] Clean exit when replay completes

### Content Tracking State
- [ ] System prompt tags identical in replay vs. live
- [ ] Diffs identical in replay vs. live
- [ ] No wall-clock dependencies in state accumulation

### Replay Speed Control
- [ ] `--replay-speed` CLI flag works
- [ ] Speed=0 replays instantly
- [ ] Speed=1.0 replays at original timing

## Exit Criteria (MEDIUM confidence item: speed control UX)
- [ ] UX decisions documented: replay indicator, interactive controls, end-of-replay behavior
