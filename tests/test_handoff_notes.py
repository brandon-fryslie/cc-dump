from cc_dump.ai.handoff_notes import (
    HandoffStore,
    SECTION_ORDER,
    parse_handoff_artifact,
    render_handoff_markdown,
)


def test_parse_handoff_artifact_keeps_all_required_sections():
    artifact = parse_handoff_artifact(
        """
        {
          "sections": {
            "changed": [{"text":"Added checkpoint API","source_links":[{"message_index":2}]}],
            "decisions": [{"text":"Use staged acceptance workflow","source_links":[{"message_index":4}]}]
          }
        }
        """,
        purpose="handoff_note",
        prompt_version="v1",
        source_provider="anthropic",
        request_id="req-1",
        source_start=0,
        source_end=5,
    )
    for section_name in SECTION_ORDER:
        assert section_name in artifact.sections
    assert artifact.sections["changed"][0].source_links[0].request_id == "req-1"


def test_render_handoff_markdown_includes_required_section_headers():
    artifact = parse_handoff_artifact(
        '{"sections":{"changed":[{"text":"x","source_links":[{"message_index":1}]}]}}',
        purpose="handoff_note",
        prompt_version="v1",
        source_provider="anthropic",
        request_id="req-1",
        source_start=0,
        source_end=2,
    )
    rendered = render_handoff_markdown(artifact)
    assert "## changed" in rendered
    assert "## decisions" in rendered
    assert "## open work" in rendered
    assert "## risks" in rendered
    assert "## next steps" in rendered


def test_handoff_store_latest_by_session():
    store = HandoffStore()
    first = parse_handoff_artifact(
        '{"sections":{"changed":[{"text":"a","source_links":[{"message_index":0}]}]}}',
        purpose="handoff_note",
        prompt_version="v1",
        source_provider="anthropic",
        request_id="req-1",
        source_start=0,
        source_end=0,
    )
    second = parse_handoff_artifact(
        '{"sections":{"changed":[{"text":"b","source_links":[{"message_index":1}]}]}}',
        purpose="handoff_note",
        prompt_version="v1",
        source_provider="anthropic",
        request_id="req-2",
        source_start=1,
        source_end=1,
    )
    store.add(first)
    store.add(second)
    latest = store.latest("anthropic")
    assert latest is not None
    assert latest.handoff_id == second.handoff_id
