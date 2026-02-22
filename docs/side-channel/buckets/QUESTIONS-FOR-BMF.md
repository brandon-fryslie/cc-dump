# Questions For BMF (Per Bucket)

Purpose:
- Collect the minimum decisions where your product/operational preference matters.
- Provide default recommendations so implementation can proceed in placeholder mode.

`// [LAW:verifiable-goals] Questions are tied to concrete implementation gates.`

## Global decisions

1. Default side-channel profile for user-triggered features:
- Options: `ephemeral_default`, `cache_probe_resume`, or adaptive.
- Recommendation: adaptive (`cache_probe_resume` when source session id exists, else `ephemeral_default`).
- Why: best chance of cache hits without blocking unknown-session flows.

2. Default budget posture:
- Options: permissive, warning-first, hard-cap.
- Recommendation: warning-first with per-purpose caps + explicit override.
- Why: protects quota without making feature feel broken.

3. Default automation posture:
- Options: manual-only, hybrid, auto-first.
- Recommendation: manual-only for Medium/High cost purposes, hybrid for Low cost purposes.
- Why: keeps spend predictable early.

## Bucket 00: Core debug lane

Question:
- Should side-channel lanes be hidden by default in tab strip unless active traffic exists?
- Recommendation: yes; show only when active or when user enables "show side-channel lanes".

## Bucket 01: Purpose cost analytics

Question:
- Do you want per-lane and global rollups both visible initially, or global only?
- Recommendation: global first, lane drill-down second.

## Bucket 02: Block summaries + cache

Question:
- Which block categories should be summarized first?
- Recommendation: start with long tool results and long assistant text blocks only.

Question:
- Should summaries be generated automatically or on-demand per block?
- Recommendation: on-demand first with local cache.

## Bucket 03: Compaction strategies (exploratory)

Question:
- What constitutes acceptable compaction fidelity for you?
- Recommendation: require source-linking + user approval before any context replacement.

## Bucket 04: Proxy interception

Question:
- Do you want marker content preserved in HAR request text for debugging transparency?
- Recommendation: yes in debug builds; strip marker before upstream forwarding.

## Bucket 05: Decision ledger

Question:
- Should decision ledger updates be append-only or allow in-place edits by model output?
- Recommendation: append-only with explicit "supersedes" links.

## Bucket 06: Prompt registry

Question:
- Who owns prompt version increments (manual process vs auto on change)?
- Recommendation: manual semantic version bumps per purpose.

## Bucket 07: Budget guardrails

Question:
- Should hard caps fail closed (block feature) or degrade to fallback automatically?
- Recommendation: degrade to fallback automatically + explicit warning.

## Bucket 08: Summary checkpoints

Question:
- Trigger cadence: manual only vs periodic (every N turns)?
- Recommendation: manual and milestone-based first.

## Bucket 09: Action/deferred extraction

Question:
- Should extracted items auto-create beads tasks or require explicit approval?
- Recommendation: explicit approval always.

## Bucket 10: Handoff notes

Question:
- Standard handoff template or user-selectable templates?
- Recommendation: one standard template first.

## Bucket 11: Release notes/changelog

Question:
- Include unreleased/experimental items by default?
- Recommendation: no; require explicit include flag.

## Bucket 12: Incident timeline

Question:
- Should timeline generation include hypotheses or facts-only mode initially?
- Recommendation: facts-only default, optional hypotheses section.

## Bucket 13: Lightweight utilities

Question:
- How many utility prompts should be enabled initially?
- Recommendation: max 3-5; require purpose registration for each.

## Bucket 14: Conversation Q&A textbox

Question:
- Should whole-session scope be disabled by default?
- Recommendation: yes; require explicit scope selection each request.

## Bucket 15: Evaluation gates

Question:
- Minimum quality threshold for promotion from MVP to default-on?
- Recommendation: zero segregation leaks + budget compliance + task-specific quality threshold met on benchmark set.

## Bucket 16: Redaction/data boundaries

Question:
- Do you want a strict redaction mode that omits tool output bodies by default?
- Recommendation: yes for auto-run features; optional for manual runs.

## Research context (primary references)

- Anthropic prompt caching docs: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- HAR schema reference (`comment` and custom fields): https://w3c.github.io/web-performance/specs/HAR/Overview.html
- Claude CLI capability source for flags/profile design: local `claude --help` output (validated 2026-02-22).

