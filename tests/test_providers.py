"""Tests for provider registry and provider-family helpers."""

from cc_dump import providers


def test_provider_session_key_mapping():
    assert providers.provider_session_key("anthropic") == "__default__"


def test_complete_shape_validation_is_family_based():
    anthropic_msg = {"type": "message", "content": []}
    openai_msg = {"object": "chat.completion", "choices": []}

    assert providers.is_complete_response_for_provider("anthropic", anthropic_msg)
    assert not providers.is_complete_response_for_provider("anthropic", openai_msg)


def test_detect_provider_from_har_entry_returns_none_when_unknown_complete_shape():
    entry = {"request": {"url": "https://unknown.example/v1/chat"}}
    unknown_complete = {"foo": "bar"}

    assert (
        providers.detect_provider_from_har_entry(
            entry,
            complete_message=unknown_complete,
        )
        is None
    )
    assert (
        providers.infer_provider_from_har_entry(
            entry,
            complete_message=unknown_complete,
        )
        == providers.DEFAULT_PROVIDER_KEY
    )


def test_provider_proxy_type_defaults():
    assert providers.get_provider_spec("anthropic").proxy_type == "reverse"


def test_build_provider_proxy_env_uses_endpoint_mode():
    endpoint = providers.build_provider_endpoint(
        providers.DEFAULT_PROVIDER_KEY,
        proxy_url="http://127.0.0.1:3344",
        target="https://api.anthropic.com",
        proxy_mode="reverse",
    )
    assert providers.build_provider_proxy_env(endpoint) == {
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:3344",
    }
