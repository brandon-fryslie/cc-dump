"""Tests for provider registry and provider-family helpers."""

import cc_dump.providers as providers


def test_copilot_provider_spec_registered():
    spec = providers.get_provider_spec("copilot")
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
    assert providers.get_provider_spec("openai").proxy_type == "reverse"
    assert providers.get_provider_spec("copilot").proxy_type == "forward"


def test_build_provider_endpoint_normalizes_forward_ca_path():
    endpoint = providers.build_provider_endpoint(
        "copilot",
        proxy_url="http://127.0.0.1:4567",
        target="https://api.githubcopilot.com",
        proxy_mode="forward",
        forward_proxy_ca_cert_path=" /tmp/copilot-ca.crt ",
    )
    assert endpoint.provider_key == "copilot"
    assert endpoint.proxy_mode == "forward"
    assert endpoint.target == ""
    assert endpoint.forward_proxy_ca_cert_path == "/tmp/copilot-ca.crt"


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


def test_build_provider_endpoint_detail_lines_hide_tls_branching_outside_providers():
    endpoint = providers.build_provider_endpoint(
        "copilot",
        proxy_url="http://127.0.0.1:4567",
        target="https://ignored.example",
        proxy_mode="forward",
        forward_proxy_ca_cert_path="/tmp/copilot-ca.crt",
    )

    assert providers.build_provider_endpoint_detail_lines(endpoint) == (
        "Copilot endpoint (forward): http://127.0.0.1:4567",
        "  Usage: HTTP_PROXY=http://127.0.0.1:4567 HTTPS_PROXY=http://127.0.0.1:4567 NODE_EXTRA_CA_CERTS=/tmp/copilot-ca.crt <your-tool>",
    )


def test_resolve_forward_proxy_connect_route_validates_provider_host_boundary():
    allowed = providers.resolve_forward_proxy_connect_route(
        "copilot",
        host="api.githubcopilot.com",
        port=443,
    )
    denied = providers.resolve_forward_proxy_connect_route(
        "copilot",
        host="api.openai.com",
        port=443,
    )

    assert allowed is not None
    assert allowed.provider_key == "copilot"
    assert allowed.upstream_origin == "https://api.githubcopilot.com"
    assert denied is None
