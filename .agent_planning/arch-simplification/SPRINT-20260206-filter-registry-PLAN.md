# Sprint: filter-registry - Consolidate Filter Definitions into Single Registry
Generated: 2026-02-06
Confidence: MEDIUM: 1, LOW: 0
Status: RESEARCH REQUIRED

## Sprint Goal
Eliminate filter name duplication across 5 files by creating a single filter registry that all consumers derive from.

## Scope
**Deliverables:**
- Single filter registry defining all filters (name, type, default, keybinding, color, block types)
- All 5 current duplication sites derive from the registry
- Adding a new filter requires exactly one edit (registry entry)

## Work Items

### P0: Create filter registry and migrate all consumers
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] A single `FILTER_REGISTRY` dict/list exists in one canonical location
- [ ] Each filter entry specifies: key, display_label, filter_type (content|panel), default_state, color_index, keybinding, controlled_block_types
- [ ] `palette.py` derives `_FILTER_INDICATOR_INDEX` from registry
- [ ] `app.py` derives `active_filters` from registry (reactive properties may still be needed for Textual reactivity)
- [ ] `custom_footer.py` derives action-to-filter mapping from registry
- [ ] `rendering.py` derives `BLOCK_FILTER_KEY` from registry
- [ ] `widget_factory.py` derives filter status display from registry
- [ ] Test exists: adding a filter to the registry and forgetting a consumer file causes test failure
- [ ] All existing tests pass

#### Unknowns to Resolve
- **Where does the registry live?** Options:
  (a) New `filters.py` module — clean, but adds a file
  (b) In `formatting.py` alongside the block types it controls — co-located with the IR
  (c) In `app.py` where the reactive properties live — close to the primary consumer
  Leaning toward (a) since the registry crosses module boundaries.
- **Textual reactive properties**: `app.py` uses `reactive(False)` for each filter. Can these be generated from a registry, or does Textual require them to be class-level declarations? Needs investigation.
- **Hot-reload**: If the registry is in a reloadable module, adding a filter at runtime would work. If it's in a stable module, filter changes require restart.

#### Exit Criteria
- Registry location decided
- Textual reactive property generation investigated
- Raises to HIGH once those are resolved

## Dependencies
- Sprint 1 (dead-code-cleanup) should be complete (the "expand" → "budget" rename simplifies this)
- Sprint 2 (state-on-data) should be complete (removes the expand override complexity from the filter path)

## Risks
- Textual's reactive system may not support dynamically generated properties. If so, the registry can still centralize definitions but app.py would hand-write the properties referencing registry keys.
- Over-engineering risk: if the registry is more complex than the duplication it replaces, it's not worth it. Keep it as a simple list of dicts, not a framework.
