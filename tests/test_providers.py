"""Tests for provider registry and provider-family helpers."""

import cc_dump.providers as providers


def test_copilot_provider_spec_registered():
    spec = providers.require_provider_spec("copilot")
    assert spec.key == "copilot"
    assert spec.protocol_family == "openai"
    assert spec.tab_title == "Copilot"
    assert spec.proxy_type == "forward"


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


def test_provider_proxy_type_defaults():
    assert providers.require_provider_spec("anthropic").proxy_type == "reverse"
    assert providers.require_provider_spec("openai").proxy_type == "reverse"
    assert providers.require_provider_spec("copilot").proxy_type == "forward"


def test_build_provider_endpoint_normalizes_forward_ca_path():
    endpoint = providers.build_provider_endpoint(
        "copilot",
        proxy_url="http://127.0.0.1:4567",
        target="https://api.githubcopilot.com",
        forward_proxy_ca_cert_path=" /tmp/copilot-ca.crt ",
    )
    assert endpoint.provider_key == "copilot"
    assert endpoint.proxy_mode == "forward"
    assert endpoint.target is None
    assert endpoint.forward_proxy_ca_cert_path == "/tmp/copilot-ca.crt"


def test_build_provider_proxy_env_uses_endpoint_mode():
    endpoint = providers.build_provider_endpoint(
        providers.DEFAULT_PROVIDER_KEY,
        proxy_url="http://127.0.0.1:3344",
        target="https://api.anthropic.com",
    )
    assert providers.build_provider_proxy_env(endpoint) == {
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:3344",
    }
