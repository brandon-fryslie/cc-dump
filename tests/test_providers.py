"""Tests for provider registry and provider-family helpers."""

import cc_dump.providers as providers


def test_copilot_provider_spec_registered():
    spec = providers.require_provider_spec("copilot")
    assert spec.key == "copilot"
    assert spec.protocol_family == "openai"
    assert spec.tab_title == "Copilot"


def test_provider_session_key_mapping():
    assert providers.provider_session_key("anthropic") == "__default__"
    assert providers.provider_session_key("openai") == "openai:__default__"
    assert providers.provider_session_key("copilot") == "copilot:__default__"


def test_infer_provider_from_url_copilot():
    url = "https://api.githubcopilot.com/chat/completions"
    assert providers.infer_provider_from_url(url) == "copilot"


def test_complete_shape_validation_is_family_based():
    anthropic_msg = {"type": "message", "content": []}
    openai_msg = {"object": "chat.completion", "choices": []}

    assert providers.is_complete_response_for_provider("anthropic", anthropic_msg)
    assert not providers.is_complete_response_for_provider("anthropic", openai_msg)
    assert providers.is_complete_response_for_provider("openai", openai_msg)
    assert providers.is_complete_response_for_provider("copilot", openai_msg)
