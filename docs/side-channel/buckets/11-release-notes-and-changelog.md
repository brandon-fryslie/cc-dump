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

## Ready to start?

Yes, provided source scoping is explicit.

Definition of ready:
- generation is scoped to chosen ranges
- output format templates are reusable via prompt registry

