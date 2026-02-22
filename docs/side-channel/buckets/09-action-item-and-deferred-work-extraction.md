# 09 Action-Item And Deferred-Work Extraction

Goal:
- Extract concrete next actions and deferred work from conversation.

`// [LAW:one-type-per-behavior] Action items should use one normalized schema (owner, scope, status, source).`

## How it could work

- Run extraction prompt on selected messages/turn windows.
- Output structured items:
- action text
- priority/confidence
- optional owner
- due hint
- source links
- optionally create/update beads issues from approved items.

## Value

- Converts conversation into execution artifacts quickly.
- Prevents dropped follow-ups.

## Rough token cost

- Low-Medium per extraction pass.
- Higher only if run continuously on all turns.

## Ready to start?

Yes for manual trigger MVP.

Unknowns:
- acceptable confidence threshold for auto-suggestions

Definition of ready:
- extracted items are source-linked
- user can accept/reject items before persistence

