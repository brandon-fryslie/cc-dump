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
