# Sorted HIGH / MEDIUM Complexity Work Order

Source: `.agent_planning/COMPLEXITY-AUDIT-2026-03-06.md`

Notes:
- The audit uses `MODERATE`; this document treats that as `MEDIUM`.
- The goal here is not "highest severity first." It is "least churn overall." The ordering below front-loads deletions and seam creation that reduce the amount of code touched by later refactors.

## Ordering Principles

1. Remove dead or low-value branches before refactoring adjacent high-complexity systems.
2. Fix shared state boundaries before refactoring the features that sit on top of them.
3. Refactor leaf features before cross-cutting coordinators.
4. Leave `Hot Reload` for last because it reconstructs and rebinds almost every other subsystem.

## Sorted Work List

### 1. Handoff Note Draft
- Audit item: `16. Handoff Note Draft`
- Complexity: `MEDIUM`
- Why first: It is described as unreachable / placeholder-driven dead code inside the AI workbench area. Removing it shrinks the `ai/` surface before touching the much larger workbench controller.
- Churn avoided: prevents refactoring `AI Workbench Panel` around code that should not survive.

### 2. CycleSelector / MultiCycleSelector Widgets
- Audit item: `19. CycleSelector / MultiCycleSelector Widgets`
- Complexity: `MEDIUM`
- Why here: `CycleSelector` is coupled mainly to the launch-config UI, and `MultiCycleSelector` appears unused. Decide whether to delete or keep these widgets before reshaping the launch configuration panel.
- Churn avoided: prevents reworking `Launch Configuration System` around widget code that may be removed.

### 3. Settings Persistence
- Audit item: `27. Settings Persistence`
- Complexity: `MEDIUM`
- Why here: The audit calls out two persistence paths and split ownership between `settings_store` and direct `io/settings` writes. That is a foundational state boundary problem.
- Churn avoided: `Launch Configuration System` and parts of the TUI should not be simplified until there is one canonical persistence path.

### 4. Launch Configuration System
- Audit item: `20. Launch Configuration System`
- Complexity: `HIGH`
- Why here: Once persistence ownership is unified, the launch panel and controller can be simplified without preserving three competing "active config" representations.
- Churn avoided: avoids rewriting the panel twice, once for persistence cleanup and again for panel simplification.

### 5. Tmux Integration
- Audit item: `21. Tmux Integration`
- Complexity: `MEDIUM`
- Why here: Tmux is downstream of launch configuration and currently has duplicate sync paths. Simplifying it after launch-config cleanup lets it consume a cleaner launch/profile boundary.
- Churn avoided: avoids updating tmux behavior against launch APIs that are about to change.

### 6. Forward Proxy Mode (HTTP CONNECT)
- Audit item: `2. Forward Proxy Mode (HTTP CONNECT)`
- Complexity: `MEDIUM`
- Why here: This is the narrower proxy-layer boundary issue, especially around CONNECT tunneling and CA-path handling. It should be settled before recording/replay code that sits on the same request pipeline.
- Churn avoided: keeps proxy contract changes from rippling into HAR work twice.

### 7. HAR Recording
- Audit item: `3. HAR Recording`
- Complexity: `MEDIUM`
- Why here: The audit points out cross-domain coupling from HAR recording into AI marker extraction. Clean this after the proxy boundary but before larger AI subsystem changes.
- Churn avoided: avoids carrying proxy-layer and AI-coupling debt into later workbench refactors.

### 8. Panel System
- Audit item: `28. Panel System`
- Complexity: `MEDIUM`
- Why here: The audit identifies a hardcoded `"session"` refresh special case and notes dead panel implementations. Normalize the panel contract before touching panel-heavy features.
- Churn avoided: gives `AI Workbench Panel` and future panel cleanup one refresh protocol instead of preserving a special case.

### 9. AI Workbench Panel
- Audit item: `15. AI Workbench Panel`
- Complexity: `HIGH`
- Why here: After dead handoff code is gone and the panel contract is cleaner, the workbench can be simplified around a smaller, clearer surface. The audit explicitly recommends a `WorkbenchContext` seam.
- Churn avoided: prevents workbench changes from depending on dead handoff flows and ad hoc panel plumbing.

### 10. View Overrides
- Audit item: `31. View Overrides (Cross-Cutting Infrastructure)`
- Complexity: `HIGH`
- Why here: This is the shared mutable state that rendering, search, click handling, and keyboard actions all write into. The audit identifies it as the most heavily coupled object in the codebase.
- Churn avoided: search, expand/collapse, and rendering all get cheaper to refactor once renderer artifacts are split from user-facing view state.

### 11. 3-Level Visibility System
- Audit item: `6. 3-Level Visibility System`
- Complexity: `MEDIUM`
- Why here: The audit says this system is mostly well-structured, but it sits directly beside `ViewOverrides`. Tidy it after the shared override boundary is cleaned up, not before.
- Churn avoided: avoids revisiting visibility semantics after `ViewOverrides` changes.

### 12. Click-to-Expand/Collapse
- Audit item: `7. Click-to-Expand/Collapse`
- Complexity: `MEDIUM`
- Why here: This feature currently relies on renderer artifacts stored inside `ViewOverrides`. It should be revisited only after `ViewOverrides` is split.
- Churn avoided: prevents redoing click-state plumbing after the override model changes.

### 13. Search System
- Audit item: `13. Search System`
- Complexity: `HIGH`
- Why here: The audit describes direct access to multiple private `ConversationView` fields plus direct mutation of `ViewOverrides`. It is the first major consumer that benefits from the new seam.
- Churn avoided: avoids building a `ConversationNavigator` abstraction on top of a still-moving override model.

### 14. Follow Mode
- Audit item: `14. Follow Mode`
- Complexity: `MEDIUM`
- Why here: Follow mode is smaller, but it shares navigation and scrolling behavior with search and action handlers. Clean it after search/navigation boundaries are clearer.
- Churn avoided: prevents navigation-state churn while search decoupling is still in flight.

### 15. Rendering Pipeline
- Audit item: `8. Rendering Pipeline (Markdown, Code Highlighting, XML Collapsible)`
- Complexity: `HIGH`
- Why here: The audit says the core architecture is sound, but the file is huge and currently writes renderer artifacts back into `ViewOverrides`. Address it after the override/search seams are established.
- Churn avoided: avoids extracting renderers while their side-effect contract is still changing.

### 16. Hot Reload
- Audit item: `24. Hot Reload`
- Complexity: `HIGH`
- Why last: The audit explicitly says this controller calls into rendering, theme, settings, view store, bridge, and search. It is the highest-coupling module and should absorb the new subsystem boundaries only after those boundaries stabilize.
- Churn avoided: minimizes repeated hot-reload repair work after each upstream refactor.

## Recommended Execution Batches

### Batch A: Remove / decide low-value surface
1. Handoff Note Draft
2. CycleSelector / MultiCycleSelector Widgets

### Batch B: Launch / session ownership
3. Settings Persistence
4. Launch Configuration System
5. Tmux Integration

### Batch C: Proxy / pipeline cleanup
6. Forward Proxy Mode (HTTP CONNECT)
7. HAR Recording

### Batch D: Panel / AI surface
8. Panel System
9. AI Workbench Panel

### Batch E: View / navigation / render core
10. View Overrides
11. 3-Level Visibility System
12. Click-to-Expand/Collapse
13. Search System
14. Follow Mode
15. Rendering Pipeline
16. Hot Reload
