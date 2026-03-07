from cc_dump.ai.prompt_registry import get_prompt_spec


def test_known_purpose_returns_registered_spec():
    spec = get_prompt_spec("handoff_note")
    assert spec.purpose == "handoff_note"
    assert spec.version == "v1"
    assert "handoff note" in spec.instruction


def test_unknown_purpose_falls_back_to_utility_custom():
    spec = get_prompt_spec("totally_unknown_purpose")
    assert spec.purpose == "utility_custom"
    assert spec.version == "v1"
    assert "Process the provided context" in spec.instruction


def test_lookup_is_deterministic_for_unknown_purpose():
    spec_a = get_prompt_spec("x")
    spec_b = get_prompt_spec("x")
    assert spec_a == spec_b

def test_handoff_prompt_requires_fixed_sections():
    spec = get_prompt_spec("handoff_note")
    assert spec.purpose == "handoff_note"
    assert "strict JSON" in spec.instruction
    assert "\"changed\"" in spec.instruction
    assert "\"next_steps\"" in spec.instruction


def test_conversation_qa_prompt_declares_answer_with_sources():
    spec = get_prompt_spec("conversation_qa")
    assert spec.purpose == "conversation_qa"
    assert "strict JSON" in spec.instruction
    assert "\"answer\"" in spec.instruction
    assert "\"source_links\"" in spec.instruction

