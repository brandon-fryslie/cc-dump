from cc_dump.ai.side_channel_boundary import (
    REDACTION_POLICY_VERSION,
    apply_boundary,
    get_boundary_policy,
)
from cc_dump.ai.prompt_registry import SIDE_CHANNEL_PURPOSES


def test_policy_defined_for_all_purposes():
    for purpose in SIDE_CHANNEL_PURPOSES:
        policy = get_boundary_policy(purpose)
        assert policy.purpose == purpose
        assert policy.policy_version == REDACTION_POLICY_VERSION
        assert policy.max_prompt_chars >= 256


def test_boundary_redacts_sensitive_tokens():
    prompt = (
        "authorization: Bearer abcdef12345\n"
        "x-api-key: xyz987\n"
        "password=hunter2\n"
        "aws=AKIAABCDEFGHIJKLMNOP\n"
        "anthropic=sk-ant-1234567890abcdef\n"
    )
    result = apply_boundary(prompt, "block_summary")
    assert "Bearer abcdef12345" not in result.prompt
    assert "x-api-key: xyz987" not in result.prompt
    assert "hunter2" not in result.prompt
    assert "AKIAABCDEFGHIJKLMNOP" not in result.prompt
    assert "sk-ant-1234567890abcdef" not in result.prompt
    assert result.redactions_applied > 0
    assert result.policy_version == REDACTION_POLICY_VERSION


def test_boundary_applies_prompt_cap():
    big_prompt = "x" * 50_000
    result = apply_boundary(big_prompt, "core_debug_lane")
    assert result.truncated is True
    assert len(result.prompt) <= get_boundary_policy("core_debug_lane").max_prompt_chars
    assert result.prompt.endswith("[TRUNCATED_BY_POLICY]")
