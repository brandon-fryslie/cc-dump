import json

import cc_dump.proxies.copilot.token_manager as token_manager
from cc_dump.proxies.runtime import ProxyRuntime


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


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


def test_resolve_copilot_token_prefers_explicit_token():
    snapshot = _snapshot(proxy_copilot_token="copilot_explicit")
    token, error = token_manager.resolve_copilot_token(snapshot)
    assert error is None
    assert token == "copilot_explicit"


def test_resolve_copilot_token_uses_github_fetch(monkeypatch):
    snapshot = _snapshot(proxy_copilot_github_token="gh_token_123")

    def fake_urlopen(request, timeout=0):
        _ = request
        _ = timeout
        return _FakeHTTPResponse(
            {
                "token": "copilot_from_gh",
                "expires_at": 2_000_000_000,
                "refresh_in": 1200,
            }
        )

    monkeypatch.setattr(token_manager.urllib.request, "urlopen", fake_urlopen)
    token, error = token_manager.resolve_copilot_token(snapshot)
    assert error is None
    assert token == "copilot_from_gh"


def test_resolve_copilot_token_errors_without_any_auth():
    snapshot = _snapshot()
    token, error = token_manager.resolve_copilot_token(snapshot)
    assert token == ""
    assert "Missing" in str(error)
