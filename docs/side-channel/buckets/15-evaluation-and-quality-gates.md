# 15 Evaluation And Quality Gates

Goal:
- Define how side-channel features are evaluated before broader rollout.

`// [LAW:verifiable-goals] Each bucket must have deterministic, machine-checkable success criteria.`

## Why this should exist

- Avoid shipping features that "feel" useful but are noisy/expensive.
- Keep AI-assisted behavior measurable over time.
- Prevent regressions in quality and spend.

## How it could work

- For each purpose, define:
- task-specific acceptance checks
- quality thresholds
- token budget threshold
- fallback behavior checks
- Record evaluation runs in CI and local test harnesses.

## Example metrics

- precision/recall proxy for extraction tasks
- summary usefulness rubric score
- lane contamination count (must be zero)
- cost per successful output

## Rough token cost

- Low to Medium (depends on benchmark corpus size).
- Can be minimized with fixed evaluation corpora and periodic runs.

## Implemented now

- Per-purpose machine-verifiable thresholds:
  - canonical map in `src/cc_dump/side_channel_eval_metrics.py`
  - documentation in `docs/side-channel/EVALUATION_METRICS.md`
- Deterministic harness over fixed corpus:
  - corpus: `docs/side-channel/eval/side_channel_eval_corpus.json`
  - runner: `python -m cc_dump.side_channel_eval`
  - output artifact: `.artifacts/side_channel_eval.json`
- CI promotion gate:
  - workflow runs `--check` mode and fails on threshold regressions

## Deferred follow-ups

- Expand fixed corpus coverage as additional side-channel purposes ship.
- Track trend comparisons across runs, not only threshold pass/fail.
