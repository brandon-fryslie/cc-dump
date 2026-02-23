from cc_dump.ai.incident_timeline import (
    IncidentTimelineStore,
    parse_incident_timeline_artifact,
    render_incident_timeline_markdown,
)


def test_parse_incident_timeline_orders_entries():
    artifact = parse_incident_timeline_artifact(
        """
        {
          "facts": [
            {"timestamp":"2026-02-22T10:00:00Z","actor":"svc","action":"recover","outcome":"ok","source_links":[{"message_index":2}]},
            {"timestamp":"2026-02-22T09:00:00Z","actor":"svc","action":"error","outcome":"failed","source_links":[{"message_index":1}]}
          ]
        }
        """,
        purpose="incident_timeline",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=2,
        include_hypotheses=False,
    )
    assert len(artifact.facts) == 2
    assert artifact.facts[0].timestamp == "2026-02-22T09:00:00Z"
    assert artifact.facts[1].timestamp == "2026-02-22T10:00:00Z"
    assert artifact.hypotheses == []


def test_incident_timeline_mode_toggle_controls_hypotheses():
    payload = """
    {
      "facts": [{"timestamp":"2026-02-22T09:00:00Z","actor":"svc","action":"error","outcome":"failed","source_links":[{"message_index":1}]}],
      "hypotheses": [{"timestamp":"2026-02-22T09:05:00Z","actor":"operator","action":"suspect cache issue","outcome":"unconfirmed","source_links":[{"message_index":3}]}]
    }
    """
    facts_only = parse_incident_timeline_artifact(
        payload,
        purpose="incident_timeline",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=2,
        include_hypotheses=False,
    )
    with_hypotheses = parse_incident_timeline_artifact(
        payload,
        purpose="incident_timeline",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=2,
        include_hypotheses=True,
    )
    assert facts_only.hypotheses == []
    assert len(with_hypotheses.hypotheses) == 1


def test_render_incident_timeline_omits_hypothesis_section_in_facts_only_mode():
    artifact = parse_incident_timeline_artifact(
        '{"facts":[{"timestamp":"2026-02-22T09:00:00Z","actor":"svc","action":"error","outcome":"failed"}]}',
        purpose="incident_timeline",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=1,
        include_hypotheses=False,
    )
    rendered = render_incident_timeline_markdown(artifact, include_hypotheses=False)
    assert "## facts" in rendered
    assert "## hypotheses" not in rendered


def test_incident_timeline_store_latest_by_session():
    store = IncidentTimelineStore()
    first = parse_incident_timeline_artifact(
        '{"facts":[{"timestamp":"2026-02-22T09:00:00Z","actor":"svc","action":"error","outcome":"failed"}]}',
        purpose="incident_timeline",
        prompt_version="v1",
        source_session_id="sess-x",
        request_id="req-1",
        source_start=0,
        source_end=1,
        include_hypotheses=False,
    )
    second = parse_incident_timeline_artifact(
        '{"facts":[{"timestamp":"2026-02-22T10:00:00Z","actor":"svc","action":"recover","outcome":"ok"}]}',
        purpose="incident_timeline",
        prompt_version="v1",
        source_session_id="sess-x",
        request_id="req-2",
        source_start=2,
        source_end=3,
        include_hypotheses=False,
    )
    store.add(first)
    store.add(second)
    latest = store.latest("sess-x")
    assert latest is not None
    assert latest.timeline_id == second.timeline_id
