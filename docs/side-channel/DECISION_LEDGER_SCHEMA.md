# Decision Ledger Schema (MVP)

Canonical runtime module:
- `src/cc_dump/decision_ledger.py`

`// [LAW:one-type-per-behavior] Decision entries use one canonical shape.`
`// [LAW:one-source-of-truth] Merge/supersede semantics are owned by DecisionLedgerStore.`

## Entry fields

- `decision_id: str`
- `statement: str`
- `rationale: str`
- `alternatives: list[str]`
- `consequences: list[str]`
- `status: proposed|accepted|revised|deprecated`
- `source_links: list[{request_id, message_index}]`
- `supersedes: list[str]`
- `superseded_by: str`
- `created_at: ISO timestamp`
- `updated_at: ISO timestamp`

## Extraction payload contract

Expected model output shape:

```json
{
  "decisions": [
    {
      "decision_id": "dec_example",
      "statement": "Use queue-based routing",
      "rationale": "Simpler backpressure handling",
      "alternatives": ["callback graph"],
      "consequences": ["requires queue visibility"],
      "status": "accepted",
      "source_links": [{"message_index": 12}],
      "supersedes": []
    }
  ]
}
```

## Supersede semantics

- If entry `B` lists `supersedes=["A"]`, entry `A` is marked:
  - `status = deprecated`
  - `superseded_by = B.decision_id`
