# Sprint: model-attribution - Model Attribution Research & Implementation
Generated: 2026-02-03-140000
Confidence: HIGH: 1, MEDIUM: 2, LOW: 0
Status: PARTIALLY READY
Source: EVALUATION-20260202.md

## Sprint Goal
Determine and implement model attribution semantics for tool economics: how to correctly price tool invocations when different models may be used across turns, and whether sub-agent tool calls should be attributed separately.

## Blocked By
- SPRINT-20260203-130000-query-panel-update (needs working economics panel first)

## Scope
**Deliverables:**
- Research findings document on model attribution semantics
- Model-aware norm cost calculation in tool economics
- (If applicable) Sub-agent attribution in panel display

## Work Items

### P1 - Research: Model Consistency Within Turns [MEDIUM]

**Dependencies**: None (research can start immediately)
**Spec Reference**: ARCHITECTURE.md "Database Layer" -- turns table has `model` column
**Status Reference**: EVALUATION-20260202.md "Existing Model Economics" -- model is per-turn

#### Description
Investigate: Do all tool invocations within a single turn always use the same model? In Claude Code's typical usage:
- A turn is a single API request/response cycle
- The model is set in the request body (`"model": "claude-sonnet-4-..."`)
- All tool_use blocks in the response are from the same model
- But: sub-agents may spawn separate API calls with different models

We need to understand:
1. Can a single turn have tools processed by different models? (Almost certainly NO -- one model per API call)
2. Can sub-agent turns be identified and attributed separately?
3. Does Claude Code ever switch models mid-session? (YES -- Opus for thinking, Haiku for simple tasks)

#### Acceptance Criteria
- [ ] Document answers to the three questions above based on observed API traffic
- [ ] Determine if per-turn model attribution is sufficient (it should be)
- [ ] Identify if sub-agent detection needs separate handling

#### Unknowns to Resolve
1. **Sub-agent tool calls**: Does Claude Code's sub-agent feature create separate API turns, or are sub-agent tool calls embedded in the parent turn? Research approach: examine captured turn data in SQLite for sessions with sub-agents.
2. **Model switching frequency**: How often does Claude Code switch models within a session? Research approach: query `SELECT DISTINCT model FROM turns WHERE session_id = ?` on real session data.

#### Exit Criteria (to reach HIGH confidence)
- [ ] Observed at least 3 real sessions with tool calls and documented model patterns
- [ ] Sub-agent behavior documented with concrete examples

#### Technical Notes
- The turns table already has a `model` column that is populated from `message_start.message.model`.
- Each tool invocation is linked to exactly one turn via `turn_id`.
- A JOIN `tool_invocations.turn_id -> turns.model` gives the model for each tool invocation.
- This is likely already sufficient and the research may confirm that the Sprint 2 implementation is correct.

---

### P1 - Model-Aware Tool Pricing [HIGH]

**Dependencies**: Research above (for confidence), Sprint 2 (for working panel)
**Spec Reference**: analysis.py `ModelPricing` and `classify_model()`
**Status Reference**: EVALUATION-20260202.md "Existing Model Economics"

#### Description
Ensure the norm cost calculation in `get_tool_economics()` correctly uses the per-turn model for pricing each tool invocation. This is already partially implemented in Sprint 2's query (which JOINs with turns.model), but needs verification and possible refinement:
- If a tool is called 5 times across 3 Sonnet turns and 2 Opus turns, the norm cost should reflect the per-invocation model pricing, not an average.
- The Sprint 2 query already does this per-row, but we should verify the aggregation is correct.

#### Acceptance Criteria
- [ ] Norm cost for a tool reflects the actual model used for each invocation
- [ ] Mixed-model tools (same tool, different models) are correctly priced
- [ ] Test with mock data showing Sonnet and Opus invocations of the same tool produces correct weighted cost

#### Technical Notes
- The Sprint 2 CONTEXT already computes norm_cost per-row using `classify_model(model)`. The aggregation sums these per-row costs. This should be correct by construction.
- Verification: create a test with 2 Read calls (1 Sonnet, 1 Opus) and verify the total norm_cost equals the sum of individual model-specific costs.

---

### P2 - Sub-Agent Attribution Display [MEDIUM]

**Dependencies**: Research (P1 above)
**Spec Reference**: EVALUATION-20260202.md "cc-dump-5nd (subagent attribution)"
**Status Reference**: EVALUATION-20260202.md "Dependencies and Blockers"

#### Description
If the research reveals that sub-agent tool calls are distinguishable (e.g., by model, by tool_use_id pattern, or by some other marker), add optional grouping in the economics panel:
- Option A: Show a "Sub-agent" row in the tool economics panel
- Option B: Add a model column to the economics panel showing which model(s) each tool was called with
- Option C: Defer -- if sub-agents are not distinguishable, document this limitation

This work item is MEDIUM confidence because the approach depends on research findings.

#### Acceptance Criteria
- [ ] If sub-agents are distinguishable: panel shows sub-agent vs main-agent attribution
- [ ] If sub-agents are NOT distinguishable: document the limitation and add a TODO for when Anthropic adds sub-agent markers to the API
- [ ] No regression in existing panel functionality

#### Unknowns to Resolve
1. **Sub-agent identification**: How can cc-dump tell if a turn was from a sub-agent? Research: examine Claude Code's sub-agent API patterns. Does it use a different model? Different system prompt? Different tool set?
2. **Display design**: What's the most useful way to show sub-agent attribution? Research: talk to user about what information they want.

#### Exit Criteria (to reach HIGH confidence)
- [ ] Sub-agent turns can be identified programmatically, OR documented as not identifiable
- [ ] Display design decided and approved by user

#### Technical Notes
- Claude Code's sub-agent feature (Task tool) typically spawns separate conversations. If those go through the same proxy, they appear as separate sessions or separate turns with possibly different system prompts.
- The `tool_names` column in turns already captures the tool definitions per turn. Sub-agent turns might have a different tool set.
- This is a P2 and can be deferred if research shows sub-agents are not cleanly separable.

## Dependencies
- Blocked by Sprint 2 (needs working economics panel)
- Research item can start in parallel with Sprint 2 implementation
- Model-aware pricing is mostly done in Sprint 2, just needs verification
- Sub-agent attribution depends on research findings

## Risks
- **Sub-agent complexity**: If sub-agents are not cleanly identifiable, this sprint reduces to just verification of Sprint 2's model pricing (minimal work).
- **Scope creep**: Sub-agent attribution could become complex. Mitigation: timebox research to 2 hours, defer if no clear approach emerges.
