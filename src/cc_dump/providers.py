"""Provider registry shared across proxy, formatting, replay, and UI layers.

// [LAW:one-source-of-truth] Provider metadata and normalization live here.
// [LAW:single-enforcer] Provider-family shape checks are enforced here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


ProtocolFamily: TypeAlias = Literal["anthropic", "openai"]
ProxyMode: TypeAlias = Literal["reverse", "forward"]


@dataclass(frozen=True)
class ProviderSpec:
    """Canonical metadata for one provider integration."""

    key: str
    display_name: str
    tab_title: str
    tab_short_prefix: str
    protocol_family: ProtocolFamily
    api_paths: tuple[str, ...]
    har_request_url: str
    base_url_env: str
    proxy_type: ProxyMode
    default_target: str
    optional_proxy: bool
    url_markers: tuple[str, ...]
    client_hint: str = "<your-tool>"


@dataclass(frozen=True)
class ProviderEndpoint:
    """Resolved proxy endpoint metadata for one active provider."""

    provider_key: str
    proxy_url: str
    target: str
    proxy_mode: ProxyMode
    forward_proxy_ca_cert_path: str = ""


ProviderEndpointMap: TypeAlias = dict[str, ProviderEndpoint]


DEFAULT_PROVIDER_KEY = "anthropic"
DEFAULT_SESSION_KEY = "__default__"


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
        proxy_type="reverse",
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
        proxy_type="reverse",
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
        proxy_type="forward",
        default_target="https://api.githubcopilot.com",
        optional_proxy=True,
        url_markers=("api.githubcopilot.com", "githubcopilot.com"),
    ),
}

def build_provider_endpoint(
    provider: str,
    *,
    proxy_url: str,
    target: str,
    proxy_mode: ProxyMode,
    forward_proxy_ca_cert_path: str = "",
) -> ProviderEndpoint:
    """Build normalized endpoint metadata for one provider.

    // [LAW:single-enforcer] Endpoint normalization lives at this boundary so
    // CLI, TUI, and launchers consume one typed shape.
    """
    spec = get_provider_spec(provider)
    normalized_target = target.strip() if proxy_mode == "reverse" else ""
    normalized_ca_path = forward_proxy_ca_cert_path.strip() if proxy_mode == "forward" else ""
    return ProviderEndpoint(
        provider_key=spec.key,
        proxy_url=proxy_url.strip(),
        target=normalized_target,
        proxy_mode=proxy_mode,
        forward_proxy_ca_cert_path=normalized_ca_path,
    )


def default_provider_endpoint(host: str, port: int, target: str) -> ProviderEndpoint:
    """Build endpoint metadata for the canonical default provider."""
    return build_provider_endpoint(
        DEFAULT_PROVIDER_KEY,
        proxy_url=f"http://{host}:{port}",
        target=target,
        proxy_mode=get_provider_spec(DEFAULT_PROVIDER_KEY).proxy_type,
    )


def build_provider_proxy_env(endpoint: ProviderEndpoint) -> dict[str, str]:
    """Build launcher env vars for one provider endpoint."""
    if not endpoint.proxy_url:
        return {}
    spec = get_provider_spec(endpoint.provider_key)
    if endpoint.proxy_mode == "forward":
        env = {
            "HTTP_PROXY": endpoint.proxy_url,
            "HTTPS_PROXY": endpoint.proxy_url,
        }
        if endpoint.forward_proxy_ca_cert_path:
            env["NODE_EXTRA_CA_CERTS"] = endpoint.forward_proxy_ca_cert_path
        return env
    return {spec.base_url_env: endpoint.proxy_url}


def normalize_provider(provider: str) -> str:
    return provider.strip().lower()


def is_known_provider(provider: str) -> bool:
    return normalize_provider(provider) in _PROVIDERS


def get_provider_spec(provider: str) -> ProviderSpec:
    """Return provider spec from the canonical registry."""
    return _PROVIDERS[normalize_provider(provider)]


def all_provider_specs() -> tuple[ProviderSpec, ...]:
    return tuple(_PROVIDERS.values())


def optional_proxy_provider_specs() -> tuple[ProviderSpec, ...]:
    return tuple(spec for spec in _PROVIDERS.values() if spec.optional_proxy)


def provider_session_key(provider: str) -> str:
    """Map provider key to its default tab/session key."""
    spec = get_provider_spec(provider)
    return (
        DEFAULT_SESSION_KEY
        if spec.key == DEFAULT_PROVIDER_KEY
        else f"{spec.key}:{DEFAULT_SESSION_KEY}"
    )


def session_provider(session_key: str) -> str:
    """Resolve provider key from a session key."""
    prefix, sep, suffix = session_key.partition(":")
    is_provider_session = (
        sep == ":"
        and suffix == DEFAULT_SESSION_KEY
        and prefix in _PROVIDERS
    )
    return prefix if is_provider_session else DEFAULT_PROVIDER_KEY


def infer_provider_from_url(url: str) -> str:
    """Best-effort provider inference from request URL."""
    url_lc = url.strip().lower()
    return next(
        (
            spec.key
            for spec in _PROVIDERS.values()
            if any(marker in url_lc for marker in spec.url_markers)
        ),
        DEFAULT_PROVIDER_KEY,
    )


def infer_provider_from_complete_message(message: dict[str, object]) -> str:
    """Best-effort provider inference from complete response shape."""
    # // [LAW:dataflow-not-control-flow] Provider family is derived from response markers.
    if message.get("type") == "message":
        return "anthropic"
    if message.get("object") == "chat.completion":
        return "openai"
    return DEFAULT_PROVIDER_KEY


def is_complete_response_for_provider(provider: str, message: dict[str, object]) -> bool:
    """Validate complete-response shape for the provider family."""
    family = get_provider_spec(provider).protocol_family
    checks = {
        "anthropic": message.get("type") == "message",
        "openai": message.get("object") == "chat.completion",
    }
    return checks.get(family, False)
