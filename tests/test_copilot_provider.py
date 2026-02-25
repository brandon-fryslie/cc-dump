from cc_dump.proxies.copilot import provider
from cc_dump.proxies.runtime import ProxyRuntime


def _snapshot(**overrides):
    runtime = ProxyRuntime()
    data = {
        "proxy_provider": "copilot",
        "proxy_anthropic_base_url": "https://api.anthropic.com",
        "proxy_copilot_base_url": "https://api.githubcopilot.com",
        "proxy_copilot_token": "",
        "proxy_copilot_github_token": "",
        "proxy_copilot_account_type": "individual",
        "proxy_copilot_vscode_version": "1.99.0",
    }
    data.update(overrides)
    runtime.update_from_settings(data)
    return runtime.snapshot()


def test_prepare_messages_request_uses_explicit_copilot_token():
    snapshot = _snapshot(proxy_copilot_token="copilot_token_123")
    request, error = provider.prepare_messages_request(
        snapshot=snapshot,
        anthropic_payload={
            "model": "claude-sonnet-4-20251001",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        },
    )
    assert error is None
    assert request is not None
    assert request.url.endswith("/chat/completions")
    assert request.headers["Authorization"] == "Bearer copilot_token_123"


def test_prepare_messages_request_errors_without_auth():
    snapshot = _snapshot()
    request, error = provider.prepare_messages_request(
        snapshot=snapshot,
        anthropic_payload={
            "model": "claude-sonnet-4-20251001",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )
    assert request is None
    assert error is not None


def test_prepare_models_request_uses_explicit_copilot_token():
    snapshot = _snapshot(proxy_copilot_token="copilot_token_abc")
    request, error = provider.prepare_models_request(snapshot=snapshot)
    assert error is None
    assert request is not None
    assert request.url.endswith("/models")
    assert request.headers["Authorization"] == "Bearer copilot_token_abc"


def test_prepare_usage_request_requires_github_token():
    snapshot = _snapshot()
    request, error = provider.prepare_usage_request(snapshot=snapshot)
    assert request is None
    assert error is not None


def test_prepare_usage_request_builds_github_api_call():
    snapshot = _snapshot(
        proxy_copilot_github_token="gho_123",
        proxy_copilot_vscode_version="1.92.0",
    )
    request, error = provider.prepare_usage_request(snapshot=snapshot)
    assert error is None
    assert request is not None
    assert request.url.endswith("/copilot_internal/user")
    assert request.method == "GET"
    assert request.headers["authorization"] == "token gho_123"
    assert request.headers["editor-version"] == "vscode/1.92.0"


def test_prepare_openai_chat_request_passthrough():
    snapshot = _snapshot(proxy_copilot_token="copilot_token_abc")
    request, error = provider.prepare_openai_chat_request(
        snapshot=snapshot,
        openai_payload={
            "model": "claude-sonnet-4",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )
    assert error is None
    assert request is not None
    assert request.stream is True
    assert request.url.endswith("/chat/completions")
    assert request.headers["Authorization"] == "Bearer copilot_token_abc"


def test_prepare_openai_embeddings_request():
    snapshot = _snapshot(proxy_copilot_token="copilot_token_abc")
    request, error = provider.prepare_openai_embeddings_request(
        snapshot=snapshot,
        openai_payload={
            "model": "text-embedding-3-large",
            "input": "hello world",
        },
    )
    assert error is None
    assert request is not None
    assert request.url.endswith("/embeddings")
    assert request.stream is False
    assert request.headers["Authorization"] == "Bearer copilot_token_abc"


def test_prepare_messages_request_uses_configured_vscode_version():
    snapshot = _snapshot(
        proxy_copilot_token="copilot_token_123",
        proxy_copilot_vscode_version="1.91.0",
    )
    request, error = provider.prepare_messages_request(
        snapshot=snapshot,
        anthropic_payload={
            "model": "claude-sonnet-4-20251001",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        },
    )
    assert error is None
    assert request is not None
    assert request.headers["editor-version"] == "vscode/1.91.0"


def test_count_tokens_for_messages_fallback_on_error(monkeypatch):
    def _raise(_payload):
        raise ValueError("bad payload")

    monkeypatch.setattr(provider, "translate_to_openai", _raise)
    count = provider.count_tokens_for_messages(
        {
            "model": "claude-sonnet-4-20251001",
            "messages": [{"role": "user", "content": "hello"}],
        }
    )
    assert count == 1
