# 14 Conversation Q&A Textbox (Selectable Scope)

Goal:
- Let users ask arbitrary questions about conversation history, optionally over selected subsets of messages.

`// [LAW:capabilities-over-context] User chooses explicit scope; avoid sending omniscient full history by default.`

## How it could work

- UI textbox with scope selector:
- current lane only
- selected messages
- selected checkpoint window
- whole session (explicit)
- Request includes purpose=`conversation_qa` and scope metadata.
- Response links back to relevant source message ranges.

## Value

- High flexibility for ad-hoc analysis.
- Turns archive into an interactive memory layer.

## Rough token cost

- Selected subset: Low-Medium.
- Whole session queries: Medium-High.
- Repeated broad queries can become very expensive.

## Ready to start?

Yes for constrained MVP.

MVP constraints:
- require explicit scope selection
- default to selected messages only
- enforce budget guardrails and fallback

Definition of ready:
- responses include source references
- scope and estimated cost are visible pre-send

