# 11 Release Notes And Changelog Generation

Goal:
- Draft release notes/changelog entries from session history and decisions.

`// [LAW:one-source-of-truth] Generated release notes should reference canonical source ranges/commits where possible.`

## How it could work

- Inputs: selected sessions/checkpoints + optional git context.
- Output variants:
- user-facing highlights
- technical changelog
- known issues/upgrade notes
- Keep drafting step separate from final approval/edit.

## Value

- Reduces repetitive writing.
- Improves consistency of release communication.

## Rough token cost

- Low-Medium for targeted releases.
- Medium if broad history scans are included.

## Implemented now

- Deterministic template contract:
  - required sections (`user_highlights`, `technical_changes`, `known_issues`, `upgrade_notes`)
  - prompt-versioned schema in prompt registry
- Scoped generation flow:
  - `DataDispatcher.generate_release_notes(...)`
  - explicit source range (`source_start/source_end`) honored
  - source-linked entries retained in artifact
- Review/edit/export handoff:
  - latest draft retrieval + snapshot APIs
  - draft markdown rendering by variant (`user_facing`, `technical`)

## Deferred follow-ups

- Optional git-context enrichment for version tags/commit grouping.
- UI draft editor integration.
