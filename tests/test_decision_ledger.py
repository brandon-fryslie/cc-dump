from cc_dump.decision_ledger import (
    DecisionLedgerStore,
    parse_decision_entries,
)


def test_parse_decision_entries_from_json_payload():
    text = """
    {
      "decisions": [
        {
          "decision_id": "dec_auth_v2",
          "statement": "Use OAuth token refresh flow",
          "rationale": "Reduce re-auth churn",
          "alternatives": ["manual login"],
          "consequences": ["more background requests"],
          "status": "accepted",
          "source_links": [{"message_index": 4}],
          "supersedes": []
        }
      ]
    }
    """
    entries = parse_decision_entries(text, request_id="req-1")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.decision_id == "dec_auth_v2"
    assert entry.statement == "Use OAuth token refresh flow"
    assert entry.status == "accepted"
    assert entry.source_links[0].request_id == "req-1"
    assert entry.source_links[0].message_index == 4


def test_parse_decision_entries_invalid_json_returns_empty():
    assert parse_decision_entries("not-json", request_id="req-1") == []


def test_supersede_marks_previous_decision_deprecated():
    store = DecisionLedgerStore()
    initial = parse_decision_entries(
        '{"decisions":[{"decision_id":"dec_a","statement":"Use sqlite","status":"accepted"}]}',
        request_id="req-1",
    )
    store.upsert_many(initial)

    replacing = parse_decision_entries(
        '{"decisions":[{"decision_id":"dec_b","statement":"Use in-memory store","status":"accepted","supersedes":["dec_a"]}]}',
        request_id="req-2",
    )
    store.upsert_many(replacing)
    by_id = {entry.decision_id: entry for entry in store.snapshot()}

    assert by_id["dec_a"].status == "deprecated"
    assert by_id["dec_a"].superseded_by == "dec_b"
    assert by_id["dec_b"].status == "accepted"
