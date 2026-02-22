# 14 Conversation Q&A Textbox (Selectable Scope)

Goal:
- Let users ask arbitrary questions about conversation history, optionally over selected subsets of messages.

`// [LAW:capabilities-over-context] User chooses explicit scope; avoid sending omniscient full history by default.`

## How it could work

- UI textbox with scope selector:
- selected range (default)
- selected message indices
- whole session (explicit only)
- Request includes purpose=`conversation_qa` and scope metadata.
- Response links back to relevant source message ranges.

## Value

- High flexibility for ad-hoc analysis.
- Turns archive into an interactive memory layer.

## Rough token cost

- Selected subset: Low-Medium.
- Whole session queries: Medium-High.
- Repeated broad queries can become very expensive.

## Implemented now

- Scoped request contract:
  - `QAScope` model with explicit whole-session confirmation requirement
  - default mode is selected-range scope (narrow by default)
- Q&A execution path:
  - `DataDispatcher.ask_conversation_question(...)`
  - source-linked response parsing (`answer` + `source_links`)
  - fallback-safe behavior on disable/guardrail/error
- Budget estimate integration:
  - pre-send estimate generated for each Q&A request (`QABudgetEstimate`)
  - send flow carries estimate alongside answer result

## Deferred follow-ups

- UI textbox + scope selector wiring.
- Visual pre-send budget badge in the compose/send flow.
