# 09 Action-Item And Deferred-Work Extraction

Goal:
- Extract concrete next actions and deferred work from conversation.

`// [LAW:one-type-per-behavior] Action items should use one normalized schema (owner, scope, status, source).`

## How it could work

- Run extraction prompt on selected messages/turn windows.
- Output structured items:
  - kind (`action`/`deferred`)
  - action text
  - confidence
  - optional owner
  - due hint
  - source links
- stage extracted items for review first (no automatic persistence)
- persist only accepted items; optional beads linking hook on acceptance

## Value

- Converts conversation into execution artifacts quickly.
- Prevents dropped follow-ups.

## Rough token cost

- Low-Medium per extraction pass.
- Higher only if run continuously on all turns.

## Implemented now

- Canonical normalized schema:
  - `ActionWorkItem` + `ActionSourceLink`
  - parser: `parse_action_items(...)`
  - review/persistence store: `ActionItemStore`
- Dispatcher workflow:
  - extraction: `DataDispatcher.extract_action_items(...)`
  - review access: `DataDispatcher.pending_action_items(...)`
  - explicit persistence: `DataDispatcher.accept_action_items(...)`
  - accepted snapshot: `DataDispatcher.accepted_action_items_snapshot(...)`
- Optional beads issue linking:
  - explicit `create_beads=True` confirmation gate on acceptance
  - default bridge adapter creates `bd` tasks and stores linked issue IDs

## Deferred follow-ups

- UI review panel for accept/reject actions.
- Confidence threshold defaults and auto-suggest policy.
