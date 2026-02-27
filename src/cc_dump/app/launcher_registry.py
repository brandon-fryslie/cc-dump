"""Launcher registry for tmux-integrated CLI tools.

// [LAW:one-source-of-truth] Launcher metadata and defaults live in one registry.
// [LAW:one-type-per-behavior] One LauncherSpec type models all tools.
"""

from __future__ import annotations

from dataclasses import dataclass

import cc_dump.providers


@dataclass(frozen=True)
class LauncherSpec:
    """Canonical launch metadata for one CLI tool."""

    key: str
    display_name: str
    default_command: str
    process_names: tuple[str, ...]
    provider_key: str | None = None
    supports_model_flag: bool = False
    supports_resume_flag: bool = False


DEFAULT_LAUNCHER_KEY = "claude"


# // [LAW:one-source-of-truth] All tmux launcher presets are declared here.
_LAUNCHERS: dict[str, LauncherSpec] = {
    "claude": LauncherSpec(
        key="claude",
        display_name="Claude",
        default_command="claude",
        process_names=("claude", "clod"),
        provider_key="anthropic",
        supports_model_flag=True,
        supports_resume_flag=True,
    ),
    "copilot": LauncherSpec(
        key="copilot",
        display_name="Copilot",
        default_command="copilot",
        process_names=("copilot", "github-copilot-cli"),
        provider_key="copilot",
        supports_model_flag=False,
        supports_resume_flag=False,
    ),
}


def normalize_launcher_key(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _LAUNCHERS else DEFAULT_LAUNCHER_KEY


def get_launcher_spec(key: str) -> LauncherSpec:
    normalized = normalize_launcher_key(key)
    return _LAUNCHERS[normalized]


def all_launcher_specs() -> tuple[LauncherSpec, ...]:
    return tuple(_LAUNCHERS.values())


def launcher_keys() -> tuple[str, ...]:
    return tuple(spec.key for spec in all_launcher_specs())


def build_proxy_env(
    spec: LauncherSpec,
    provider_endpoints: dict[str, dict[str, object]] | None,
) -> dict[str, str]:
    """Build environment mapping for launcher from available proxy endpoints."""
    if spec.provider_key is None or provider_endpoints is None:
        return {}

    endpoint = provider_endpoints.get(spec.provider_key)
    if not isinstance(endpoint, dict):
        return {}

    proxy_url = str(endpoint.get("proxy_url", "") or "").strip()
    if not proxy_url:
        return {}

    provider = cc_dump.providers.get_provider_spec(spec.provider_key)
    return {provider.base_url_env: proxy_url}
