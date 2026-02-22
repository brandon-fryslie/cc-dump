from cc_dump.utility_catalog import UtilityRegistry, fallback_utility_output


def test_registry_is_bounded_and_ids_unique():
    specs = UtilityRegistry().list()
    assert 1 <= len(specs) <= 5
    ids = [spec.utility_id for spec in specs]
    assert len(ids) == len(set(ids))


def test_each_utility_has_lifecycle_policy_metadata():
    for spec in UtilityRegistry().list():
        assert spec.owner
        assert spec.budget_cap_tokens > 0
        assert spec.success_metric
        assert spec.removal_criteria
        assert spec.fallback_behavior


def test_fallback_outputs_are_non_empty_for_registered_utilities():
    messages = [{"role": "assistant", "content": "Implemented side-channel cache routing and tests."}]
    for spec in UtilityRegistry().list():
        text = fallback_utility_output(spec.utility_id, messages)
        assert isinstance(text, str)
        assert text.strip()
