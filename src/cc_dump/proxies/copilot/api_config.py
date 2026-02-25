"""Copilot API configuration helpers.

Ported from the reference proxy implementation's core header/base-url behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


COPILOT_VERSION = "0.26.7"
EDITOR_PLUGIN_VERSION = f"copilot-chat/{COPILOT_VERSION}"
USER_AGENT = f"GitHubCopilotChat/{COPILOT_VERSION}"
API_VERSION = "2025-04-01"


@dataclass(frozen=True)
class CopilotAuthConfig:
    token: str
    account_type: str = "individual"
    base_url: str = ""
    vscode_version: str = "1.99.0"


def resolve_copilot_base_url(config: CopilotAuthConfig) -> str:
    configured = str(config.base_url or "").strip().rstrip("/")
    if configured:
        return configured
    account_type = str(config.account_type or "individual").strip().lower()
    if account_type == "individual":
        return "https://api.githubcopilot.com"
    return f"https://api.{account_type}.githubcopilot.com"


def build_copilot_headers(
    *,
    config: CopilotAuthConfig,
    vision: bool = False,
    agent_initiator: bool = False,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {config.token}",
        "content-type": "application/json",
        "accept": "application/json",
        "copilot-integration-id": "vscode-chat",
        "editor-version": f"vscode/{config.vscode_version}",
        "editor-plugin-version": EDITOR_PLUGIN_VERSION,
        "user-agent": USER_AGENT,
        "openai-intent": "conversation-panel",
        "x-github-api-version": API_VERSION,
        "x-request-id": str(uuid4()),
        "x-vscode-user-agent-library-version": "electron-fetch",
        "X-Initiator": "agent" if agent_initiator else "user",
    }
    if vision:
        headers["copilot-vision-request"] = "true"
    return headers
