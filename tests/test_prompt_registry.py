from cc_dump.prompt_registry import get_prompt_spec


def test_known_purpose_returns_registered_spec():
    spec = get_prompt_spec("block_summary")
    assert spec.purpose == "block_summary"
    assert spec.version == "v1"
    assert "Summarize" in spec.instruction


def test_unknown_purpose_falls_back_to_utility_custom():
    spec = get_prompt_spec("totally_unknown_purpose")
    assert spec.purpose == "utility_custom"
    assert spec.version == "v1"
    assert "Process the provided context" in spec.instruction


def test_lookup_is_deterministic_for_unknown_purpose():
    spec_a = get_prompt_spec("x")
    spec_b = get_prompt_spec("x")
    assert spec_a == spec_b


def test_action_extraction_prompt_requires_strict_json():
    spec = get_prompt_spec("action_extraction")
    assert spec.purpose == "action_extraction"
    assert "strict JSON" in spec.instruction
    assert "\"kind\":\"action|deferred\"" in spec.instruction


def test_handoff_prompt_requires_fixed_sections():
    spec = get_prompt_spec("handoff_note")
    assert spec.purpose == "handoff_note"
    assert "strict JSON" in spec.instruction
    assert "\"changed\"" in spec.instruction
    assert "\"next_steps\"" in spec.instruction


def test_incident_timeline_prompt_declares_facts_and_hypotheses():
    spec = get_prompt_spec("incident_timeline")
    assert spec.purpose == "incident_timeline"
    assert "strict JSON" in spec.instruction
    assert "\"facts\"" in spec.instruction
    assert "\"hypotheses\"" in spec.instruction
