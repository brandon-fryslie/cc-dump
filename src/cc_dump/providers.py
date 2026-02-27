"""Provider registry shared across proxy, formatting, replay, and UI layers.

// [LAW:one-source-of-truth] Provider metadata and normalization live here.
// [LAW:single-enforcer] Provider-family shape checks are enforced here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    """Canonical metadata for one provider integration."""

    key: str
    display_name: str
    tab_title: str
    tab_short_prefix: str
    protocol_family: str  # "anthropic" | "openai"
    api_paths: tuple[str, ...]
    har_request_url: str
    base_url_env: str
    default_target: str
    optional_proxy: bool
    url_markers: tuple[str, ...]
    client_hint: str = "<your-tool>"


DEFAULT_PROVIDER_KEY = "anthropic"


# // [LAW:one-source-of-truth] All supported providers are declared in this registry.
_PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        key="anthropic",
        display_name="Anthropic",
        tab_title="Claude",
        tab_short_prefix="ANT",
        protocol_family="anthropic",
        api_paths=("/v1/messages",),
        har_request_url="https://api.anthropic.com/v1/messages",
        base_url_env="ANTHROPIC_BASE_URL",
        default_target="https://api.anthropic.com",
        optional_proxy=False,
        url_markers=("api.anthropic.com",),
        client_hint="claude",
    ),
    "openai": ProviderSpec(
        key="openai",
        display_name="OpenAI",
        tab_title="OpenAI",
        tab_short_prefix="OAI",
        protocol_family="openai",
        api_paths=("/v1/chat/completions", "/chat/completions"),
        har_request_url="https://api.openai.com/v1/chat/completions",
        base_url_env="OPENAI_BASE_URL",
        default_target="https://api.openai.com/v1",
        optional_proxy=True,
        url_markers=("api.openai.com",),
        client_hint="openai-api",
    ),
    "copilot": ProviderSpec(
        key="copilot",
        display_name="Copilot",
        tab_title="Copilot",
        tab_short_prefix="CPL",
        protocol_family="openai",
        api_paths=("/chat/completions", "/v1/chat/completions"),
        har_request_url="https://api.githubcopilot.com/chat/completions",
        base_url_env="COPILOT_PROXY_URL",
        default_target="https://api.githubcopilot.com",
        optional_proxy=True,
        url_markers=("api.githubcopilot.com", "githubcopilot.com"),
    ),
}


def normalize_provider(provider: str) -> str:
    return str(provider or "").strip().lower()


def is_known_provider(provider: str) -> bool:
    return normalize_provider(provider) in _PROVIDERS


def get_provider_spec(provider: str) -> ProviderSpec:
    """Return provider spec with explicit default fallback."""
    key = normalize_provider(provider)
    return _PROVIDERS.get(key, _PROVIDERS[DEFAULT_PROVIDER_KEY])


def require_provider_spec(provider: str) -> ProviderSpec:
    """Return provider spec or raise for unknown provider keys."""
    key = normalize_provider(provider)
    if key not in _PROVIDERS:
        raise ValueError(f"unknown provider: {provider!r}")
    return _PROVIDERS[key]


def all_provider_specs() -> tuple[ProviderSpec, ...]:
    return tuple(_PROVIDERS.values())


def optional_proxy_provider_specs() -> tuple[ProviderSpec, ...]:
    return tuple(spec for spec in _PROVIDERS.values() if spec.optional_proxy)


def provider_session_key(provider: str, default_session_key: str = "__default__") -> str:
    """Map provider key to its default tab/session key."""
    spec = get_provider_spec(provider)
    if spec.key == DEFAULT_PROVIDER_KEY:
        return default_session_key
    return f"{spec.key}:__default__"


def session_provider(
    session_key: str,
    default_session_key: str = "__default__",
) -> str:
    """Resolve provider key from a session key."""
    if session_key == default_session_key:
        return DEFAULT_PROVIDER_KEY
    prefix, sep, suffix = session_key.partition(":")
    if sep and suffix == "__default__" and prefix in _PROVIDERS:
        return prefix
    return DEFAULT_PROVIDER_KEY


def infer_provider_from_url(url: str) -> str:
    """Best-effort provider inference from request URL."""
    url_lc = str(url or "").strip().lower()
    for spec in _PROVIDERS.values():
        if any(marker in url_lc for marker in spec.url_markers):
            return spec.key
    return DEFAULT_PROVIDER_KEY


def infer_provider_from_complete_message(message: object) -> str:
    """Best-effort provider inference from complete response shape."""
    if not isinstance(message, dict):
        return DEFAULT_PROVIDER_KEY
    if message.get("type") == "message":
        return "anthropic"
    if message.get("object") == "chat.completion":
        # OpenAI-family payloads are ambiguous across providers; use the
        # canonical family representative for fallback classification.
        return "openai"
    return DEFAULT_PROVIDER_KEY


def is_complete_response_for_provider(provider: str, message: object) -> bool:
    """Validate complete-response shape for the provider family."""
    if not isinstance(message, dict):
        return False
    family = get_provider_spec(provider).protocol_family
    if family == "anthropic":
        return message.get("type") == "message"
    if family == "openai":
        return message.get("object") == "chat.completion"
    return False
