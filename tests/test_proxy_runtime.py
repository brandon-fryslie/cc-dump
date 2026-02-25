from cc_dump.proxies.runtime import (
    PROVIDER_ANTHROPIC,
    ProxyRuntime,
)


def test_proxy_runtime_updates_from_settings():
    runtime = ProxyRuntime()
    snapshot = runtime.update_from_settings(
        {
            "proxy_provider": "copilot",
            "proxy_anthropic_base_url": "https://api.anthropic.com/",
            "proxy_copilot_base_url": "https://api.githubcopilot.com/",
            "proxy_copilot_token": "tok_123",
            "proxy_copilot_account_type": "business",
            "proxy_copilot_rate_limit_seconds": "15",
            "proxy_copilot_rate_limit_wait": "true",
        }
    )
    assert snapshot.provider == "copilot"
    assert snapshot.get_text("proxy_anthropic_base_url") == "https://api.anthropic.com"
    assert snapshot.get_text("proxy_copilot_base_url") == "https://api.githubcopilot.com"
    assert snapshot.get_text("proxy_copilot_token") == "tok_123"
    assert snapshot.get_text("proxy_copilot_account_type") == "business"
    assert snapshot.get_text("proxy_copilot_vscode_version", "1.99.0") == "1.99.0"
    assert snapshot.get_int("proxy_copilot_rate_limit_seconds") == 15
    assert snapshot.get_bool("proxy_copilot_rate_limit_wait") is True
    assert snapshot.active_base_url == "https://api.githubcopilot.com"
    assert snapshot.reverse_proxy_enabled is True


def test_proxy_runtime_normalizes_invalid_provider_fields():
    runtime = ProxyRuntime()
    snapshot = runtime.update_from_settings(
        {
            "proxy_provider": "invalid",
            "proxy_anthropic_base_url": " https://a.example.com/ ",
            "proxy_copilot_base_url": " https://c.example.com/ ",
            "proxy_copilot_token": "  token  ",
            "proxy_copilot_account_type": "unknown",
            "proxy_copilot_rate_limit_seconds": "-5",
            "proxy_copilot_rate_limit_wait": "not-a-bool",
        }
    )
    assert snapshot.provider == "invalid"
    assert snapshot.get_text("proxy_anthropic_base_url") == "https://a.example.com"
    assert snapshot.get_text("proxy_copilot_base_url") == "https://c.example.com"
    assert snapshot.get_text("proxy_copilot_account_type") == "unknown"
    assert snapshot.get_int("proxy_copilot_rate_limit_seconds") == 0
    assert snapshot.get_bool("proxy_copilot_rate_limit_wait") is False
    assert snapshot.active_base_url == "https://a.example.com"


def test_proxy_runtime_unknown_provider_uses_provider_specific_base_url():
    runtime = ProxyRuntime()
    snapshot = runtime.update_from_settings(
        {
            "proxy_provider": "custom",
            "proxy_anthropic_base_url": "https://anthropic.example.com/",
            "proxy_custom_base_url": "https://custom.example.com/",
        }
    )
    assert snapshot.provider == "custom"
    assert snapshot.active_base_url == "https://custom.example.com"
