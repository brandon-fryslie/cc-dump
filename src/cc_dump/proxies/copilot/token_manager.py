"""Copilot token resolver with GitHub-token refresh fallback."""

from __future__ import annotations

from dataclasses import dataclass
import json
import threading
import time
import urllib.request
import urllib.error

from cc_dump.proxies.runtime import ProxyRuntimeSnapshot


COPILOT_VERSION = "0.26.7"
EDITOR_PLUGIN_VERSION = f"copilot-chat/{COPILOT_VERSION}"
USER_AGENT = f"GitHubCopilotChat/{COPILOT_VERSION}"
API_VERSION = "2025-04-01"
GITHUB_API_BASE_URL = "https://api.github.com"


@dataclass
class _CachedCopilotToken:
    token: str
    expires_at_unix: int
    refresh_at_unix: int


_CACHE_LOCK = threading.Lock()
_CACHE_BY_GITHUB_TOKEN: dict[str, _CachedCopilotToken] = {}


def build_github_headers(github_token: str, *, vscode_version: str = "1.99.0") -> dict[str, str]:
    return {
        "content-type": "application/json",
        "accept": "application/json",
        "authorization": f"token {github_token}",
        "editor-version": f"vscode/{vscode_version}",
        "editor-plugin-version": EDITOR_PLUGIN_VERSION,
        "user-agent": USER_AGENT,
        "x-github-api-version": API_VERSION,
        "x-vscode-user-agent-library-version": "electron-fetch",
    }


def _fetch_copilot_token(github_token: str, *, vscode_version: str) -> _CachedCopilotToken:
    request = urllib.request.Request(
        f"{GITHUB_API_BASE_URL}/copilot_internal/v2/token",
        headers=build_github_headers(github_token, vscode_version=vscode_version),
        method="GET",
    )
    response = urllib.request.urlopen(request, timeout=30)
    payload = json.loads(response.read().decode("utf-8"))
    token = str(payload.get("token", "") or "").strip()
    expires_at = int(payload.get("expires_at", 0) or 0)
    refresh_in = int(payload.get("refresh_in", 0) or 0)
    now = int(time.time())
    if expires_at <= 0:
        expires_at = now + max(300, refresh_in)
    refresh_at = now + max(30, refresh_in - 60)
    return _CachedCopilotToken(
        token=token,
        expires_at_unix=expires_at,
        refresh_at_unix=refresh_at,
    )


def resolve_copilot_token(snapshot: ProxyRuntimeSnapshot) -> tuple[str, str | None]:
    """Resolve active Copilot bearer token from settings or GitHub fallback."""
    explicit = snapshot.get_text("proxy_copilot_token")
    if explicit:
        return explicit, None

    github_token = snapshot.get_text("proxy_copilot_github_token")
    if not github_token:
        return "", "Missing proxy_copilot_token and proxy_copilot_github_token"

    now = int(time.time())
    with _CACHE_LOCK:
        cached = _CACHE_BY_GITHUB_TOKEN.get(github_token)
        if cached is not None and cached.token and now < cached.refresh_at_unix:
            return cached.token, None

    try:
        refreshed = _fetch_copilot_token(
            github_token,
            vscode_version=snapshot.get_text("proxy_copilot_vscode_version", "1.99.0") or "1.99.0",
        )
    except urllib.error.HTTPError as e:
        return "", f"Failed to fetch Copilot token from GitHub: HTTP {e.code}"
    except Exception as e:  # pragma: no cover - defensive
        return "", f"Failed to fetch Copilot token from GitHub: {e}"

    if not refreshed.token:
        return "", "GitHub Copilot token endpoint returned an empty token"

    with _CACHE_LOCK:
        _CACHE_BY_GITHUB_TOKEN[github_token] = refreshed
    return refreshed.token, None
