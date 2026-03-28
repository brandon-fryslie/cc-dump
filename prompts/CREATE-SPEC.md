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

Write to `./spec/` with this organization:

| File | Covers |
|------|--------|
| `spec/INDEX.md` | Table of contents with one-line summary per file. Status tracker showing which files are draft/reviewed. |
| `spec/proxy.md` | HTTP proxy behavior: what gets intercepted, how requests/responses are handled, port assignment, TLS, provider routing |
| `spec/events.md` | Event types, their fields, ordering guarantees, the event lifecycle of a single API call |
| `spec/formatting.md` | The FormattedBlock IR: every block type, its fields, when it's produced, what data it carries. The system prompt tracking/diffing behavior. Tool correlation. |
| `spec/visibility.md` | The 3-level visibility system: categories, levels, expansion states, defaults, keyboard cycling, click behavior, how blocks map to categories |
| `spec/rendering.md` | What each block looks like at each visibility level (collapsed/expanded). Truncation limits. The dispatch model (without specifying implementation). Visual indicators (arrows, color bars, icons). |
| `spec/navigation.md` | All keyboard shortcuts, vim-style navigation, panel cycling, follow mode, search. Mouse interactions (click, double-click, shift-click, right-click). |
| `spec/recording.md` | HAR recording format, what's captured, replay behavior, session storage paths, CLI flags for recording/replay, known divergences between live and replay |
| `spec/analytics.md` | What aggregate data is tracked (tokens, tools, costs), what panels display it, panel modes, how data flows from events to aggregates |
| `spec/sessions.md` | Session identity, multi-session model (if applicable), tmux integration, launch configs, the `run` subcommand |
| `spec/cli.md` | Complete CLI interface: all flags, subcommands, environment variables, exit codes, startup sequence |
| `spec/hot-reload.md` | Hot-reload behavior from the user's perspective: what triggers it, what survives, what doesn't, the stable/reloadable boundary as a contract |
| `spec/themes.md` | Color system, theme variables, palette generation, semantic colors, how colors are assigned to content types |
| `spec/panels.md` | Side panel system: what panels exist, what each shows, panel modes, how to cycle them |
| `spec/search.md` | Search functionality: how to invoke, what's searchable, highlight behavior, navigation between matches |
| `spec/filters.md` | Filter system beyond visibility: content filters, how filter state interacts with rendering |
| `spec/export.md` | Dump/export functionality: what formats, what's included, how to trigger |
| `spec/errors.md` | Error display, error indicator behavior, how proxy/API errors surface in the UI |

## Execution Model: Parallel Agents

You orchestrate three phases using parallel subagents. Do not write spec files yourself — delegate to agents and aggregate their work.

### Phase 1: Assessment (you, the orchestrator)

1. Read `spec/INDEX.md` (if it exists) to see what's been written and its status
2. For each existing spec file, quickly scan what's there and what's incomplete
3. Decide what work to assign this iteration. You have two modes:
   - **Breadth pass:** Many spec files need to be created or are empty. Assign each to a different agent.
   - **Depth pass:** Existing specs need deepening or correction. Assign focused areas.

### Phase 2: Spec Writing (up to 250 parallel subagents)

Launch subagents in parallel. Each agent:
- Is assigned **one spec file** (or one major section of a large spec file)
- Is a **general-purpose expert in software architecture and UX** — not a code-reading robot
- Must **read the actual source code** for their assigned area. No speculation. Every claim must be traceable to code read this session. If you cannot confirm a behavior from source, leave it out — omission is always better than a guess.
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

**Assignment strategy:**
- For `events.md`: read `pipeline/event_types.py`, `pipeline/proxy.py`, `pipeline/router.py`
- For `formatting.md`: read `core/formatting.py`, `core/formatting_impl.py`, `core/special_content.py`
- For `visibility.md`: read `tui/category_config.py`, `tui/view_overrides.py`, `tui/action_config.py`, `tui/action_handlers.py`
- For `rendering.md`: read `tui/rendering.py`, `tui/rendering_impl.py`
- For `navigation.md`: read `tui/app.py` (bindings), `tui/input_modes.py`, `tui/location_navigation.py`, `tui/follow_mode.py`
- For `cli.md`: read `cli.py`, `__main__.py`, `cli_presentation.py`, `app/launch_config.py`
- For `recording.md`: read `pipeline/har_recorder.py`, `pipeline/har_replayer.py`, `io/sessions.py`
- For `analytics.md`: read `app/analytics_store.py`, `core/analysis.py`, `core/token_counter.py`, `tui/panel_renderers.py`
- For `sessions.md`: read `io/sessions.py`, `app/domain_store.py`, `app/tmux_controller.py`, `app/launch_config.py`
- For `hot-reload.md`: read `app/hot_reload.py`, `tui/hot_reload_controller.py`
- For `themes.md`: read `core/palette.py`, `tui/theme_controller.py`, docs/THEME_*.md
- For `panels.md`: read `tui/panel_registry.py`, `tui/panel_renderers.py`, `tui/session_panel.py`, `tui/info_panel.py`
- For `search.md`: read `tui/search.py`, `tui/search_controller.py`
- For `filters.md`: read `core/filter_registry.py`, `tui/category_config.py`
- For `export.md`: read `tui/dump_export.py`, `tui/dump_formatting.py`
- For `errors.md`: read `app/error_models.py`, `tui/error_indicator.py`
- For `proxy.md`: read `pipeline/proxy.py`, `pipeline/proxy_flow.py`, `pipeline/forward_proxy_tls.py`, `providers.py`

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
7. Summarize what was done this iteration and what remains for the next

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

> Last verified against: <commit hash or "not yet">

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

## Priority Order for New Specs

If starting fresh, build in this order (each builds on the previous):
1. `events.md` — the foundation; everything flows from events
2. `formatting.md` — the IR that events produce
3. `visibility.md` — how blocks are shown/hidden
4. `rendering.md` — what blocks look like
5. `navigation.md` — how users interact
6. `cli.md` — how the app is started
7. `recording.md` — persistence layer
8. Everything else in any order

On the first iteration, launch agents for items 1–7 in parallel (they can be written concurrently since they cover independent code areas; cross-references will be reconciled during review). Launch remaining spec agents for items 8+ in the same batch if capacity allows.

## Existing Documentation to Cross-Reference

These files contain architectural and product information. Use them as context, but verify claims against code — docs can be stale:
- `CLAUDE.md` — developer guide, architecture overview
- `docs/PROJECT_SPEC.md` — goals and design decisions
- `docs/PRODUCT_DECISIONS.md` — features that are staying
- `docs/ARCHITECTURE.md` — system design
- `docs/QUICK_REFERENCE.md` — keyboard shortcuts and visibility system
- `docs/THEME_COLOR_SYSTEM.md`, `docs/THEME_VARIABLE_REFERENCE.md` — color system
- `docs/HOT_RELOAD_ARCHITECTURE.md` — hot-reload contracts
- `docs/multi-session-architecture.md` — session model (may be proposal, not implemented)

## Convergence Signals

You're converging when:
- Cross-references between spec files are consistent (e.g., block types listed in `formatting.md` match those referenced in `rendering.md`)
- Review agents find only nitpicks, no accuracy issues or missing behavior
- Every spec file's Overview clearly explains *why* the feature exists, not just what it does
- You can read through the spec end-to-end and it tells a coherent story of a tool built for a specific purpose

You're NOT converging when:
- Spec files contradict each other
- Spec files read like reference manuals instead of design documents — they list features without explaining the problems those features solve
