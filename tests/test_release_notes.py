from cc_dump.release_notes import (
    RELEASE_NOTE_SECTIONS,
    ReleaseNotesStore,
    parse_release_notes_artifact,
    render_release_notes_markdown,
)


def test_parse_release_notes_artifact_has_all_sections():
    artifact = parse_release_notes_artifact(
        """
        {
          "sections": {
            "user_highlights": [{"title":"Faster summaries","detail":"Added cache-aware path","source_links":[{"message_index":1}]}],
            "technical_changes": [{"title":"Dispatcher","detail":"Added release-note generation","source_links":[{"message_index":2}]}]
          }
        }
        """,
        purpose="release_notes",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=4,
    )
    for section in RELEASE_NOTE_SECTIONS:
        assert section in artifact.sections
    assert artifact.sections["user_highlights"][0].source_links[0].request_id == "req-1"


def test_render_release_notes_variants_are_deterministic():
    artifact = parse_release_notes_artifact(
        '{"sections":{"user_highlights":[{"title":"A","detail":"B"}],"technical_changes":[{"title":"C","detail":"D"}]}}',
        purpose="release_notes",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=2,
    )
    user_md = render_release_notes_markdown(artifact, variant="user_facing")
    technical_md = render_release_notes_markdown(artifact, variant="technical")
    assert "prompt_version:v1" in user_md
    assert "## user highlights" in user_md
    assert "## technical changes" not in user_md
    assert "## technical changes" in technical_md
    assert render_release_notes_markdown(artifact, variant="technical") == technical_md


def test_release_notes_store_latest_by_session():
    store = ReleaseNotesStore()
    first = parse_release_notes_artifact(
        '{"sections":{"user_highlights":[{"title":"first","detail":"v1"}]}}',
        purpose="release_notes",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-1",
        source_start=0,
        source_end=0,
    )
    second = parse_release_notes_artifact(
        '{"sections":{"user_highlights":[{"title":"second","detail":"v2"}]}}',
        purpose="release_notes",
        prompt_version="v1",
        source_session_id="sess-1",
        request_id="req-2",
        source_start=1,
        source_end=1,
    )
    store.add(first)
    store.add(second)
    latest = store.latest("sess-1")
    assert latest is not None
    assert latest.artifact_id == second.artifact_id


def test_artifact_id_changes_when_prompt_version_changes():
    kwargs = dict(
        text='{"sections":{"user_highlights":[{"title":"same","detail":"payload"}]}}',
        purpose="release_notes",
        source_session_id="sess-2",
        request_id="req-same",
        source_start=0,
        source_end=1,
    )
    v1 = parse_release_notes_artifact(prompt_version="v1", **kwargs)
    v2 = parse_release_notes_artifact(prompt_version="v2", **kwargs)
    assert v1.artifact_id != v2.artifact_id
