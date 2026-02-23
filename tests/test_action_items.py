from cc_dump.ai.action_items import ActionItemStore, parse_action_items


def test_parse_action_items_from_json():
    payload = """
    {
      "items": [
        {
          "kind": "action",
          "text": "Add regression test for queue routing",
          "confidence": 0.9,
          "owner": "bmf",
          "due_hint": "this sprint",
          "source_links": [{"message_index": 3}]
        },
        {
          "kind": "deferred",
          "text": "Revisit compaction cadence",
          "confidence": 0.5,
          "source_links": [{"message_index": 5}]
        }
      ]
    }
    """
    items = parse_action_items(payload, request_id="req-1")
    assert len(items) == 2
    assert items[0].kind == "action"
    assert items[0].source_links[0].request_id == "req-1"
    assert items[0].source_links[0].message_index == 3
    assert items[1].kind == "deferred"
    assert items[1].source_links[0].message_index == 5


def test_parse_action_items_invalid_json_returns_empty():
    assert parse_action_items("not-json", request_id="req-1") == []


def test_accept_requires_explicit_item_selection():
    store = ActionItemStore()
    items = parse_action_items(
        '{"items":[{"kind":"action","text":"Ship checkpoint UI","source_links":[{"message_index":1}]}]}',
        request_id="req-1",
    )
    batch_id = store.stage(items)
    assert store.accepted_snapshot() == []

    accepted = store.accept(batch_id=batch_id, item_ids=[items[0].item_id])
    assert len(accepted) == 1
    assert accepted[0].status == "accepted"
    assert len(store.accepted_snapshot()) == 1


def test_accept_with_beads_hook_records_issue_id():
    store = ActionItemStore()
    items = parse_action_items(
        '{"items":[{"kind":"action","text":"Create beads epic","source_links":[{"message_index":2}]}]}',
        request_id="req-2",
    )
    batch_id = store.stage(items)
    accepted = store.accept(
        batch_id=batch_id,
        item_ids=[items[0].item_id],
        beads_hook=lambda _item: "cc-dump-123",
    )
    assert accepted[0].beads_issue_id == "cc-dump-123"


def test_accept_subset_leaves_unselected_items_unpersisted():
    store = ActionItemStore()
    items = parse_action_items(
        (
            '{"items":['
            '{"kind":"action","text":"Ship checkpoint UI","source_links":[{"message_index":1}]},'
            '{"kind":"deferred","text":"Revisit perf audit","source_links":[{"message_index":2}]}'
            ']}'
        ),
        request_id="req-3",
    )
    batch_id = store.stage(items)
    accepted = store.accept(batch_id=batch_id, item_ids=[items[0].item_id])
    assert len(accepted) == 1
    snapshot = store.accepted_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].item_id == items[0].item_id
    assert all(item.item_id != items[1].item_id for item in snapshot)
