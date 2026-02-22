# 10 Handoff Note Generation

Goal:
- Generate concise handoff notes for next session/operator.

`// [LAW:behavior-not-structure] Output quality should be judged by handoff usability, not internal prompt mechanics.`

## How it could work

- Input: selected range or latest checkpoint window.
- Output sections:
- changed
- decisions
- open work
- risks
- next steps
- Save as durable note artifact with source links.

## Value

- Faster context recovery.
- Better collaboration continuity.

## Rough token cost

- Usually Low-Medium (small targeted context).
- Can become High if run over entire long histories repeatedly.

## Implemented now

- Standard handoff artifact contract with required sections and source links.
- Dispatcher generation flow:
  - `DataDispatcher.generate_handoff_note(...)`
  - fallback artifact when side-channel disabled/blocked/error
- Durable in-memory artifacts for resume continuity:
  - `DataDispatcher.latest_handoff_note(...)`
  - `DataDispatcher.handoff_note_snapshot(...)`

## Deferred follow-ups

- UI surface for generating/inspecting handoff notes.
- Optional persistent-on-disk storage strategy.
