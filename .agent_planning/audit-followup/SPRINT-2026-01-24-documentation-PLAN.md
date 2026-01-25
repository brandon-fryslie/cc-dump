# Sprint: documentation - Create Foundational Documentation
Generated: 2026-01-24
Confidence: HIGH: 2, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Create ARCHITECTURE.md and PROJECT_SPEC.md to provide strategic foundation for sprint planning and new contributor onboarding.

## Scope
**Deliverables:**
- ARCHITECTURE.md documenting system design and patterns
- PROJECT_SPEC.md defining scope, users, and non-goals

## Work Items

### P0: Create ARCHITECTURE.md
**Confidence: HIGH**

**Content Outline:**
1. **Overview**: What cc-dump is architecturally
2. **Component Diagram**: proxy → queue → router → subscribers
3. **Data Flow**: Request capture → event distribution → display/storage
4. **Key Design Decisions**:
   - Why event-driven (decoupling, multiple subscribers)
   - Why FormattedBlock IR (separation of concerns)
   - Why SQLite (local, queryable, no external deps)
   - Why hot-reload (development iteration)
5. **Module Responsibilities**: One paragraph per module
6. **Threading Model**: Main thread vs router thread vs proxy threads
7. **Extension Points**: How to add new block types, new subscribers

**Acceptance Criteria:**
- [ ] Diagram showing proxy → queue → router → [display, store]
- [ ] Each module's single responsibility documented
- [ ] Threading model explained
- [ ] Hot-reload architecture explained
- [ ] New contributor can understand system in <10 minutes

**Technical Notes:**
- Use ASCII diagrams (no external image dependencies)
- Reference actual file paths
- Keep concise - this is a map, not a tutorial

### P1: Create PROJECT_SPEC.md
**Confidence: HIGH**

**Content Outline:**
1. **Purpose**: What cc-dump does and why
2. **Target Users**: Who benefits from this tool
3. **Core Features**: What it provides
4. **Non-Goals**: What it explicitly doesn't do
5. **Success Criteria**: How to know if it's working
6. **Terminology**: Key terms defined

**Acceptance Criteria:**
- [ ] Clear one-sentence purpose statement
- [ ] Target users explicitly named (Claude Code developers, API debuggers)
- [ ] 5-7 core features listed
- [ ] 3-5 non-goals listed (e.g., not for production, not authenticated)
- [ ] Success criteria are verifiable

**Technical Notes:**
- This is the strategic "north star" for sprint planning
- Should be stable (not updated frequently)
- Validates that sprints align with project purpose

## Dependencies
- None (independent of code changes)

## Risks
- **Scope creep**: Keep documents focused on essentials
- **Staleness**: Design for stability, not constant updates

## File Locations

```
/Users/bmf/code/cc-dump/
├── ARCHITECTURE.md    # NEW
├── PROJECT_SPEC.md    # NEW
├── README.md          # Existing (usage-focused)
└── src/cc_dump/
```

## Success Metrics
- New contributor can understand project purpose in <2 minutes (PROJECT_SPEC.md)
- New contributor can understand architecture in <10 minutes (ARCHITECTURE.md)
- Sprint planning can reference these docs for strategic alignment
