# CREATE-SPEC: Iterative Specification Generator for cc-dump

You are building a detailed functional specification for cc-dump in `./spec/*.md` files. This prompt is designed to be run iteratively — each invocation should make the spec more complete and more accurate by reading the actual codebase and reconciling what the spec says with what the code does.

## Your Mission

Produce specification files that a developer could use to rewrite cc-dump from scratch without access to the current source code. The spec describes **what the software does** (behavior, contracts, data shapes, user-facing interactions), not how it's implemented internally. Implementation details belong in architecture docs, not here.

## Spec File Structure

Write to `./spec/` with this organization:

| File | Covers |
|------|--------|
| `spec/INDEX.md` | Table of contents with one-line summary per file. Status tracker showing which files are draft/reviewed/verified. |
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

You do NOT need to create all files in one pass. Prioritize depth over breadth.

## Execution Model: Massive Parallelism

This prompt is designed for execution with heavy parallelism. You are the **orchestrator**. You do not write specs yourself — you coordinate subagents that do.

### Parallelism Budget
- **Spec writing:** Up to **250 parallel subagents** for reading code and writing spec files
- **Review:** Up to **10 parallel review agents** for cross-checking specs against code and each other
- **You (orchestrator):** Coordinate, aggregate, and apply fixes

### How to Use Parallelism

**Writing phase:** Each spec file is independent. Launch one subagent per spec file (or per major section of a large spec file). Each subagent reads the relevant source files, writes its spec, and returns. Subagents do NOT need to coordinate with each other during writing — cross-file consistency is resolved in the review phase.

**Subagent assignment pattern:** When launching a writing subagent, give it:
1. The spec file it owns (e.g., `spec/events.md`)
2. The source files it should read (e.g., `src/cc_dump/pipeline/event_types.py`, `src/cc_dump/pipeline/proxy.py`)
3. Any existing spec content to update (if this is a subsequent iteration)
4. The writing standards and file format from this prompt
5. Explicit instruction: "Write the spec file. Read code first. Do not speculate."

**Review phase:** After all writing subagents complete, launch up to 10 review agents in parallel. Each reviewer gets a different review lens (see Phase 5 below). Reviewers return findings as structured lists. You then aggregate findings, deduplicate, rank by value, and apply the best corrections directly to the spec files.

## Iterative Convergence Protocol

Each time you run, follow this cycle:

### Phase 1: Assess Current State
1. Read `spec/INDEX.md` (if it exists) to see what's been written and its status
2. Skim existing spec files to note gaps, staleness, and `[UNVERIFIED]` tags
3. Determine the work plan: which files need creation, which need deepening, which need correction

### Phase 2: Read Code + Write Specs (Parallel — up to 250 subagents)

Launch subagents in parallel. Each subagent:

4. Reads the actual source files for its assigned area. **Does not speculate.** Every claim in the spec must be traceable to code the subagent read.
5. Pays special attention to:
   - Data types and their fields (these are contractual)
   - Default values and initial state
   - Edge cases and boundary conditions
   - What happens when things go wrong (errors, empty states, missing data)
   - Ordering and sequencing guarantees
6. Writes or updates its spec file using this structure:
   ```markdown
   # <Title>

   > Status: draft | reviewed | verified
   > Last verified against: <commit hash or "not yet">

   ## Overview
   One paragraph: what this area does from the user's perspective.

   ## <Sections>
   Detailed specification organized by concept.
   ```
7. Uses tables for enumerated things (block types, key bindings, CLI flags)
8. Uses examples for complex interactions (show input → output)
9. Marks anything uncertain with `[UNVERIFIED]` — a signal for the next iteration

**Subagent source file assignments** (adjust based on what exists — use Glob/Grep to discover):

| Spec file | Primary source files to read |
|-----------|------------------------------|
| `events.md` | `pipeline/event_types.py`, `pipeline/proxy.py`, `pipeline/proxy_flow.py`, `pipeline/router.py` |
| `formatting.md` | `core/formatting.py`, `core/formatting_impl.py`, `core/analysis.py`, `core/special_content.py`, `core/segmentation.py` |
| `visibility.md` | `tui/category_config.py`, `tui/view_overrides.py`, `tui/action_config.py`, `tui/action_handlers.py`, `app/view_store.py` |
| `rendering.md` | `tui/rendering.py`, `tui/rendering_impl.py`, `tui/widget_factory.py` |
| `navigation.md` | `tui/app.py`, `tui/action_handlers.py`, `tui/action_config.py`, `tui/input_modes.py`, `tui/location_navigation.py` |
| `cli.md` | `cli.py`, `cli_presentation.py`, `__main__.py`, `app/launch_config.py` |
| `recording.md` | `pipeline/har_recorder.py`, `pipeline/har_replayer.py`, `io/sessions.py` |
| `analytics.md` | `app/analytics_store.py`, `tui/panel_renderers.py`, `core/token_counter.py` |
| `sessions.md` | `io/sessions.py`, `app/domain_store.py`, `tui/session_panel.py`, `app/tmux_controller.py`, `tui/stream_registry.py` |
| `hot-reload.md` | `app/hot_reload.py`, `tui/hot_reload_controller.py`, `docs/HOT_RELOAD_ARCHITECTURE.md` |
| `themes.md` | `core/palette.py`, `tui/theme_controller.py`, `docs/THEME_COLOR_SYSTEM.md`, `docs/THEME_VARIABLE_REFERENCE.md` |
| `panels.md` | `tui/panel_registry.py`, `tui/panel_renderers.py`, `tui/info_panel.py`, `tui/keys_panel.py`, `tui/session_panel.py`, `tui/settings_panel.py`, `tui/debug_settings_panel.py`, `tui/launch_config_panel.py` |
| `search.md` | `tui/search.py`, `tui/search_controller.py` |
| `filters.md` | `core/filter_registry.py`, `tui/category_config.py`, `tui/view_overrides.py` |
| `export.md` | `tui/dump_export.py`, `tui/dump_formatting.py` |
| `errors.md` | `app/error_models.py`, `tui/error_indicator.py` |
| `proxy.md` | `pipeline/proxy.py`, `pipeline/proxy_flow.py`, `pipeline/forward_proxy_tls.py`, `pipeline/response_assembler.py`, `providers.py` |

### Phase 3: Update Index
10. After all writing subagents return, update `spec/INDEX.md` with the current state of all files

### Phase 4: Parallel Review (up to 10 review agents)

Launch review agents in parallel. Each gets ALL spec files but a **different review lens**:

| Reviewer # | Lens | What it checks |
|------------|------|----------------|
| 1 | **Completeness** | Are there behaviors in the code not captured in any spec? Spot-check 5-10 source files against their spec coverage. |
| 2 | **Cross-reference consistency** | Do block types in `formatting.md` match those in `rendering.md` and `visibility.md`? Do key bindings in `navigation.md` match those in `cli.md`? |
| 3 | **Precision** | Find vague language ("various", "some", "etc.") and flag where concrete values should replace it. Find missing field types, missing defaults. |
| 4 | **Behavior vs. implementation** | Flag any spec text that describes HOW something is implemented rather than WHAT it does. Apply the test: "would changing the implementation require updating this text?" |
| 5 | **Edge cases** | For each spec, identify 3-5 edge cases not yet documented (empty states, error paths, boundary values, concurrent operations). |
| 6 | **Examples** | Are there enough concrete examples? Flag sections that describe complex state transitions or visual output without showing an example. |
| 7 | **Implementability** | Could someone implement each spec area from the spec alone? Flag sections where critical information is missing. |
| 8 | **Accuracy spot-check** | Pick 10-15 specific claims across specs. Read the relevant source code. Verify or refute each claim. |
| 9 | **UNVERIFIED resolution** | Find all `[UNVERIFIED]` tags. For each, read the relevant code and determine the correct answer. Return resolved values. |
| 10 | **Coherence** | Read all specs end-to-end as a narrative. Flag logical gaps, ordering problems, or areas where a reader would be confused. |

Each reviewer returns a structured list:
```
## Findings from Reviewer N: <Lens Name>

### Critical (must fix)
- [file:section] Finding description. Suggested fix: ...

### Important (should fix)
- [file:section] Finding description. Suggested fix: ...

### Minor (nice to have)
- [file:section] Finding description. Suggested fix: ...
```

### Phase 5: Aggregate + Apply

After all reviewers return:

11. Collect all findings. Deduplicate (multiple reviewers may flag the same issue).
12. Rank by category: apply all Critical fixes, then Important fixes. Minor fixes apply if they're quick and clearly correct.
13. For conflicting suggestions, prefer the one backed by a code citation.
14. Apply fixes directly to the spec files. Do NOT defer fixes to the next iteration — the whole point of parallel review is to converge within this iteration.
15. Update `spec/INDEX.md` status for files that received review fixes (draft → reviewed).

## Writing Standards

**Be precise about data.** Don't say "includes metadata" — say "includes `model` (string, e.g. 'claude-sonnet-4-20250514'), `max_tokens` (int), `stop_reason` (string | null), `stream` (bool)."

**Specify defaults.** Don't say "categories have visibility levels" — say "Default levels at startup: user=FULL, assistant=FULL, tools=SUMMARY, system=SUMMARY, budget=EXISTENCE, metadata=EXISTENCE, headers=EXISTENCE."

**Describe state transitions.** Don't say "pressing a key toggles visibility" — say "Pressing `3` cycles tools visibility: EXISTENCE→SUMMARY→FULL→EXISTENCE. Pressing `#` (Shift+3) toggles between SUMMARY↔FULL without passing through EXISTENCE."

**Show concrete examples.** For rendering specs, show what actual output looks like at each level. For event specs, show a complete event sequence for a typical API call.

**Document edge cases.** What happens with empty tool results? What if a system prompt section is removed between requests? What if the proxy can't connect to the target?

## What Belongs in Spec vs. Not

**IN spec (behavior/contract):**
- "Pressing `g` scrolls to the first line and disables follow mode"
- "ToolUseBlock carries: name (str), input_size (int), tool_use_id (str), detail (str)"
- "At SUMMARY level, consecutive tool use/result pairs are collapsed into a single summary line showing tool counts"

**NOT in spec (implementation):**
- "render_line() uses binary search over turn offsets"
- "The palette uses golden-angle spacing in HSL"
- "Stable modules use `import cc_dump.module` instead of `from cc_dump.module import func`"

The line: if changing the implementation (but not the behavior) would require updating the spec, the spec is too implementation-specific.

## Priority and Dependency Order

With parallel subagents, all spec files can be written simultaneously on the first pass. However, **review agents** should understand the conceptual dependency order so they can trace cross-references in the right direction:

```
events.md          ← foundation: all other specs reference event types
  ↓
formatting.md      ← defines the IR that rendering/visibility specs reference
  ↓
visibility.md      ← defines the level/category model that rendering uses
  ↓
rendering.md       ← depends on block types (formatting) + levels (visibility)
  ↓
navigation.md      ← depends on visibility (key bindings cycle levels)
  ↓
cli.md             ← depends on sessions, recording (CLI flags reference them)
recording.md       ← depends on events (what's captured)
  ↓
everything else    ← independent, reference the above as needed
```

On **subsequent iterations**, if time is limited, prioritize deepening specs higher in this graph — errors there cascade into downstream specs.

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
- All `[UNVERIFIED]` tags from prior iterations have been resolved
- All spec files have status "reviewed" or "verified"
- Cross-references between spec files are consistent (e.g., block types listed in `formatting.md` match those referenced in `rendering.md`)
- You can read through the spec end-to-end and it tells a coherent story

You're NOT converging when:
- You're adding new `[UNVERIFIED]` tags faster than resolving old ones
- Spec files contradict each other
- You find behavior in code that isn't captured anywhere in the spec
