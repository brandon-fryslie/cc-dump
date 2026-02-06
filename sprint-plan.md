Sprint Plan Summary: Retool surview → Surview

Total Sprints: 9 | Critical Path: 1 → 2 → 3 → 4 → 5 → 9
┌────────┬────────────────────┬─────────────────┬──────────────────────┬──────────────────────────────────────────────┐
│ Sprint │        Name        │     Status      │      Confidence      │               Key Deliverable                │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 1      │ Rename package     │ READY           │ HIGH: 4              │ surview → surview, remove tiktoken           │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 2      │ Delete LLM code    │ READY           │ HIGH: 3              │ Delete analysis.py, token_counter.py, 6 test │
│        │                    │                 │                      │  files                                       │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 3      │ Proxy + Event      │ PARTIALLY READY │ HIGH: 2, MED: 2      │ Generic proxy, THE CONTRACT for all          │
│        │ Schema             │                 │                      │ downstream                                   │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 4      │ Formatting IR      │ PARTIALLY READY │ HIGH: 3, MED: 1      │ New block types (JsonBodyBlock,              │
│        │                    │                 │                      │ SSEEventBlock, etc.)                         │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 5      │ TUI Rewrite        │ PARTIALLY READY │ HIGH: 3, MED: 2      │ New renderers, simplified filters (h/b/s/f)  │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 6      │ Database           │ PARTIALLY READY │ HIGH: 2, MED: 1      │ New requests table, generic store            │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 7      │ HAR Rewrite        │ READY           │ HIGH: 3              │ Generic recording/replay (simpler than       │
│        │                    │                 │                      │ current!)                                    │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 8      │ tmux Orchestration │ RESEARCH        │ HIGH: 1, MED: 1,     │ surview wrap -- <command>                    │
│        │                    │ REQUIRED        │ LOW: 1               │                                              │
├────────┼────────────────────┼─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ 9      │ Tests              │ PARTIALLY READY │ HIGH: 2, MED: 2      │ Full test suite for generic HTTP proxy       │
└────────┴────────────────────┴─────────────────┴──────────────────────┴──────────────────────────────────────────────┘
Key Change From Original Plan

The evaluation found that Phases 3-7 cannot be a single unit. The proxy rewrite (Sprint 3) defines the event schema
contract that everything else depends on. The dependency chain is:

Sprint 1 (rename) → Sprint 2 (delete) → Sprint 3 (proxy/events)
↓
Sprint 4 (IR)
↓
Sprint 5 (TUI) ←── Sprint 6 (DB)  [parallel]
↓         ←── Sprint 7 (HAR) [parallel]
Sprint 9 (tests)

Sprint 8 (tmux) is independent after Sprint 5

Files

.agent_planning/surview-retool/
├── EVALUATION-20260206.md          (full codebase evaluation)
├── SPRINT-01-rename-package-*      (PLAN, DOD, CONTEXT)
├── SPRINT-02-delete-llm-code-*     (PLAN, DOD, CONTEXT)
├── SPRINT-03-proxy-event-schema-*  (PLAN, DOD, CONTEXT)
├── SPRINT-04-formatting-ir-*       (PLAN, DOD, CONTEXT)
├── SPRINT-05-tui-rewrite-*         (PLAN, DOD)
├── SPRINT-06-database-*            (PLAN, DOD)
├── SPRINT-07-har-rewrite-*         (PLAN, DOD)
├── SPRINT-08-tmux-orchestration-*  (PLAN, DOD)
└── SPRINT-09-tests-*               (PLAN, DOD)

Options:
1. Approve all — start implementing Sprint 1
2. Approve HIGH confidence only (Sprints 1, 2, 7) — discuss others
3. Revise specific sprint
4. Reject and restart

