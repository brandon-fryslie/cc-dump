# Definition of Done: model-attribution
Generated: 2026-02-03-140000
Status: PARTIALLY READY
Plan: SPRINT-20260203-140000-model-attribution-PLAN.md

## Acceptance Criteria

### Model Consistency Research
- [ ] Documented: "Do all tools in a turn use the same model?" with evidence from real sessions
- [ ] Documented: "Can sub-agent turns be identified?" with evidence
- [ ] Documented: "Model switching frequency" with real data
- [ ] Findings captured in a research note (can be inline in this file or separate doc)

### Model-Aware Tool Pricing
- [ ] Test with mock data: 2 Read calls (1 Sonnet at $3/MTok input, 1 Opus at $5/MTok input) produces correct distinct costs
- [ ] Norm cost aggregation matches sum of per-invocation costs (not averaged)
- [ ] Edge case: tool with 0 token counts shows 0 norm cost (not NaN or error)

### Sub-Agent Attribution (conditional)
- [ ] IF identifiable: panel distinguishes sub-agent vs main-agent tool calls
- [ ] IF NOT identifiable: limitation documented, TODO added for future API support
- [ ] No regression in economics panel for sessions without sub-agents

## Exit Criteria (for MEDIUM confidence items)
- [ ] Research questions answered with concrete evidence
- [ ] Sub-agent identification approach decided (implement, defer, or impossible)
- [ ] If implementing: design approved by user before coding

## Verification
- [ ] `uv run pytest` passes
- [ ] `just lint` passes
- [ ] Manual verification with real multi-model session data
