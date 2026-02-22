# 10 Handoff Note Generation

Goal:
- Generate concise handoff notes for next session/operator.

`// [LAW:behavior-not-structure] Output quality should be judged by handoff usability, not internal prompt mechanics.`

## How it could work

- Input: selected range or latest checkpoint window.
- Output sections:
- what changed
- decisions made
- unfinished work
- known risks/blockers
- immediate next steps
- Save as durable note artifact with source links.

## Value

- Faster context recovery.
- Better collaboration continuity.

## Rough token cost

- Usually Low-Medium (small targeted context).
- Can become High if run over entire long histories repeatedly.

## Ready to start?

Yes for user-triggered MVP.

Definition of ready:
- notes are concise, structured, and source-linked
- recipients can resume work without reading full transcript

