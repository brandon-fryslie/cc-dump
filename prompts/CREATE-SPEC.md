# CREATE-SPEC: Iterative Specification Generator for cc-dump

You are the **orchestrator** for building a detailed functional specification of cc-dump in `./spec/*.md` files. You do not write spec files yourself — you coordinate a fleet of parallel subagents who read code and write specs, then a fleet of review agents who verify accuracy, and finally you apply corrections. This prompt is designed to be run iteratively — each invocation should make the spec more complete and more accurate.

## Your Mission

Produce specification files that a developer could use to rewrite cc-dump from scratch without access to the current source code. The spec describes **what the software does** and critically **why it does it** — the user problem each feature solves, the design trade-off each behavior represents. Implementation details belong in architecture docs, not here.

## The "Why" Lens

Every feature exists because someone needed something. The spec must capture that motivation. Before documenting *what* a feature does, each agent must understand and articulate *why* it exists:

- **Why does the visibility system have 3 levels instead of just show/hide?** Because API traffic is overwhelming — users need progressive disclosure to start with a clean view and drill into detail on demand.
- **Why does system prompt tracking use content hashing and diffs?** Because system prompts are the most interesting and least observable part of Claude Code's behavior, and they change subtly between requests.
- **Why is there a two-stage pipeline (formatting → rendering)?** Because separating "what data exists" from "how it looks" enables hot-reload of either layer independently, testing without a TUI, and potential non-TUI consumers.

This "why" framing must appear in every spec file's Overview section and should inform how features are grouped and described. Don't just list capabilities — explain the user workflows and problems they serve. A reader should finish each spec file understanding not just the feature surface but the design intent behind it.

## Spec File Structure

Write to `./spec/` with this organization

## Execution Model: Parallel Agents

You orchestrate all phases using parallel subagents.

### Phase 1: Assessment (you, the orchestrator)

1. Use parallel subagents to deeply study the codebase and determine what needs to be assessed

### Phase 2: Spec Writing (up to 250 parallel subagents)

Launch subagents in parallel. Each agent:
- Is a **general-purpose expert in software architecture and UX** — not a code-reading robot
- Must **read the actual source code**. No speculation. Every claim must be traceable to code read this session. If you cannot confirm a behavior from source, leave it out — omission is always better than a guess.
- Must understand and articulate the **"why"** before documenting the "what"
- Writes (or updates) their assigned spec file following the Writing Standards below

**Agent prompt template** (customize the assignment per agent):
```
You are a software architect writing a functional specification for one area of cc-dump,
a transparent HTTP proxy TUI for monitoring Claude Code API traffic.

YOUR ASSIGNMENT: Write/update `spec/<file>.md` covering: <brief scope description>

CONTEXT: cc-dump exists because Claude Code is opaque — users can't see the system prompts,
tool definitions, token usage, or caching behavior behind their conversations. cc-dump makes
all of this visible through a real-time TUI with progressive disclosure, recording/replay,
and analytics.

APPROACH:
1. First, understand WHY this feature area exists. What user problem does it solve?
   What would be painful or impossible without it?
2. Read the relevant source files to understand the actual behavior.
3. Write the spec describing behavior and contracts, framed by the user need it serves.
4. Every claim must be traceable to code you read. If you cannot confirm something
   from the source, DO NOT include it. Omission is better than speculation.

SOURCE FILES TO READ: <list of relevant source files>
EXISTING DOCS TO CROSS-REFERENCE: <list of relevant docs>
EXISTING SPEC (if updating): <current content or "new file">

<include Writing Standards section>
<include "What Belongs in Spec vs. Not" section>
```

### Phase 3: Review (up to 10 parallel review agents)

After spec-writing agents complete, launch review agents. Each reviewer:
- Is assigned **a batch of spec files** to review (distribute evenly)
- Reads the spec files AND the corresponding source code
- Produces a **structured review** with these categories:

```
## Review: spec/<file>.md

### Accuracy Issues (must fix)
- Line/section: <what's wrong> → <what code actually shows>

### Missing "Why" (should fix)
- <feature described without motivation> → <the user problem it solves>

### Missing Behavior (should fix)
- <behavior found in code but not in spec>

### Overclaims (should fix)
- <spec claims something the code doesn't actually do>

### Nitpicks (optional)
- <style, clarity, organization suggestions>
```

**Reviewer focus areas:**
- Does each spec file's Overview explain *why* this area exists, not just what it does?
- Are data types and their fields accurate against the actual code?
- Are defaults, initial states, and state transitions precisely described?
- Do cross-references between spec files agree? (e.g., block types in `formatting.md` match those in `rendering.md`)
- Are there behaviors in the code that the spec misses entirely?
- Is there anything in the spec file that doesn't actually appear in the code?  Anything hallucinated must be cleaned up!

### Phase 4: Aggregation and Correction (you, the orchestrator)

1. Collect all review results
2. Triage: group by severity (accuracy issues > missing behavior > missing "why" > nitpicks)
3. For accuracy issues and missing behavior: apply corrections directly to spec files
4. For missing "why": add motivation framing to Overview sections and relevant subsections
5. For cross-reference inconsistencies: reconcile and update all affected files
6. Update `spec/INDEX.md` with current status of all files
7. Summarize what was done this iteration

## Writing Standards

**Lead with the "why."** Every spec file Overview must answer: "What user problem does this solve? What would be painful without it?" Every major section should connect features to the workflows they enable.

**Be precise about data.** Don't say "includes metadata" — say "includes `model` (string, e.g. 'claude-sonnet-4-20250514'), `max_tokens` (int), `stop_reason` (string | null), `stream` (bool)."

**Specify defaults.** Don't say "categories have visibility levels" — say "Default levels at startup: user=FULL, assistant=FULL, tools=SUMMARY, system=SUMMARY, budget=EXISTENCE, metadata=EXISTENCE, headers=EXISTENCE."

**Be exhaustive.** Don't say "The Debug menu has functionality XYZ, and similarly, the Settings panel, etc." — define each feature independently and completely.

**Describe state transitions.** Don't say "pressing a key toggles visibility" — say "Pressing `3` cycles tools visibility: EXISTENCE→SUMMARY→FULL→EXISTENCE. Pressing `#` (Shift+3) toggles between SUMMARY↔FULL without passing through EXISTENCE."

**Show concrete examples.** For rendering specs, show what actual output looks like at each level. For event specs, show a complete event sequence for a typical API call.

**Document edge cases.** What happens with empty tool results? What if a system prompt section is removed between requests? What if the proxy can't connect to the target?

**Gaps.** If edge cases are undefined, document that as well.  Document any gaps in functionality or behavior that would be useful to understand.

**Spec file template:**
```markdown
# <Title>

## Overview
One paragraph: what user problem this area solves and why it exists.
One paragraph: what this area does from the user's perspective.

## <Sections>
Detailed specification organized by concept.
Each major section should connect to user workflows where relevant.
Include mermaid diagrams where relevent.
```

## What Belongs in Spec vs. Not

**IN spec (behavior/contract):**
- "Pressing `g` scrolls to the first line and disables follow mode"
- "ToolUseBlock carries: name (str), input_size (int), tool_use_id (str), detail (str)"
- "At SUMMARY level, consecutive tool use/result pairs are collapsed into a single summary line showing tool counts"
- "System prompt tracking exists because prompts change subtly between requests and these changes are invisible in Claude Code's UI"

**NOT in spec (implementation):**
- "render_line() uses binary search over turn offsets"
- "The palette uses golden-angle spacing in HSL"
- "Stable modules use `import cc_dump.module` instead of `from cc_dump.module import func`"

The line: if changing the implementation (but not the behavior) would require updating the spec, the spec is too implementation-specific.

## Existing Documentation to Cross-Reference

Note: existing documentation is often out of date and must NOT be relied on as ground-truth authority. 

## Convergence Signals

You're converging when:
- Cross-references between spec files are consistent (e.g., block types listed in `formatting.md` match those referenced in `rendering.md`)
- Review agents find only nitpicks, no accuracy issues or missing behavior
- Every spec file's Overview clearly explains *why* the feature exists, not just what it does
- You can read through the spec end-to-end and it tells a coherent story of a tool built for a specific purpose

You're NOT converging when:
- Spec files contradict each other
- Spec files read like reference manuals instead of design documents — they list features without explaining the problems those features solve
