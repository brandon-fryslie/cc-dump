# 05 Decision Ledger

Goal:
- Extract and maintain a structured record of decisions made in conversation.

`// [LAW:one-type-per-behavior] Represent decisions as one canonical decision entry type with fields, not ad hoc note formats.`
`// [LAW:one-source-of-truth] Ledger entry links to source messages/turns for auditability.`

## What it is

A decision entry can include:
- decision statement
- rationale
- alternatives considered
- consequences/tradeoffs
- status (`proposed`, `accepted`, `revised`, `deprecated`)
- links to source message IDs/ranges

## Use cases

- remember why architecture choices were made
- avoid re-litigating settled decisions
- generate handoff/release context quickly
- detect decision reversals over time

## Rough token cost

- Per extraction pass: Low-Medium.
- Continuous updates on every turn: Medium.

## Ready to start?

Yes for MVP.

MVP scope:
- user-triggered extraction over selected message ranges
- append/update ledger entries with source links

Unknowns:
- merge semantics when model output conflicts with existing ledger entry

Definition of ready:
- ledger entries are source-linked and queryable
- false-positive rate acceptable in pilot usage

Implementation reference:
- `docs/side-channel/DECISION_LEDGER_SCHEMA.md`
