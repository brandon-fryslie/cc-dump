"""Provider metadata shared across proxy, formatting, replay, and UI layers.

cc-dump is Anthropic-only. There is exactly one provider, so its metadata is a
single module constant rather than a keyed registry.

// [LAW:one-source-of-truth] The single provider spec lives here as ANTHROPIC.
// [LAW:no-mode-explosion] One provider means no keyed lookup: the registry that
//   parameterized over N providers collapsed to the N==1 constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class ProviderSpec:
    """Canonical metadata for the provider integration."""

    key: str
    display_name: str
    tab_title: str
    tab_short_prefix: str
    api_paths: tuple[str, ...]
    har_request_url: str
    base_url_env: str
    default_target: str
    url_markers: tuple[str, ...]
    client_hint: str = "<your-tool>"


@dataclass(frozen=True)
class ProviderEndpoint:
    """Resolved proxy endpoint metadata for the active provider."""

    provider_key: str
    proxy_url: str
    target: str


ProviderEndpointMap: TypeAlias = dict[str, ProviderEndpoint]


DEFAULT_PROVIDER_KEY = "anthropic"
DEFAULT_SESSION_KEY = "__default__"


# // [LAW:one-source-of-truth] The sole provider. All spec reads resolve here.
ANTHROPIC = ProviderSpec(
    key="anthropic",
    display_name="Anthropic",
    tab_title="Claude",
    tab_short_prefix="ANT",
    api_paths=("/v1/messages",),
    har_request_url="https://api.anthropic.com/v1/messages",
    base_url_env="ANTHROPIC_BASE_URL",
    default_target="https://api.anthropic.com",
    url_markers=("api.anthropic.com",),
    client_hint="claude",
)


def build_provider_endpoint(
    provider: str,
    *,
    proxy_url: str,
    target: str,
) -> ProviderEndpoint:
    """Build normalized endpoint metadata for the provider.

    // [LAW:single-enforcer] Endpoint normalization lives at this boundary so
    // CLI, TUI, and launchers consume one typed shape.
    """
    spec = get_provider_spec(provider)
    return ProviderEndpoint(
        provider_key=spec.key,
        proxy_url=proxy_url.strip(),
        target=target.strip(),
    )


def default_provider_endpoint(host: str, port: int, target: str) -> ProviderEndpoint:
    """Build endpoint metadata for the canonical default provider."""
    return build_provider_endpoint(
        DEFAULT_PROVIDER_KEY,
        proxy_url=f"http://{host}:{port}",
        target=target,
    )


def build_provider_proxy_env(endpoint: ProviderEndpoint) -> dict[str, str]:
    """Build launcher env vars for one provider endpoint."""
    return dict(_provider_proxy_env_items(endpoint))


def build_provider_usage_hint(endpoint: ProviderEndpoint) -> str:
    """Build one human-facing usage line suffix for a provider endpoint."""
    spec = get_provider_spec(endpoint.provider_key)
    env_text = " ".join(
        f"{key}={value}"
        for key, value in _provider_proxy_env_items(endpoint)
    )
    return f"{env_text} {spec.client_hint}".strip()


def build_provider_endpoint_detail_lines(endpoint: ProviderEndpoint) -> tuple[str, ...]:
    """Build human-facing detail lines for one provider endpoint."""
    spec = get_provider_spec(endpoint.provider_key)
    details = [f"{spec.display_name} endpoint: {endpoint.proxy_url}"]
    if endpoint.target:
        details.append(f"  Target: {endpoint.target}")
    details.append(f"  Usage: {build_provider_usage_hint(endpoint)}")
    return tuple(details)


def normalize_provider(provider: str) -> str:
    return provider.strip().lower()


def is_known_provider(provider: str) -> bool:
    return normalize_provider(provider) == DEFAULT_PROVIDER_KEY


def get_provider_spec(provider: str) -> ProviderSpec:
    """Return the provider spec.

    // [LAW:one-source-of-truth] ANTHROPIC is the only spec, so every provider key
    //   resolves to it. The `provider` argument is vestigial — it survives only
    //   because callers still thread a (constant) provider field through the
    //   event/HAR/session records; slice .5 removes the field and this argument.
    """
    return ANTHROPIC


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
        and prefix == DEFAULT_PROVIDER_KEY
    )
    return prefix if is_provider_session else DEFAULT_PROVIDER_KEY


def provider_from_url_marker(url: str) -> str | None:
    """Match provider key from URL markers, returning None when unknown."""
    url_lc = url.strip().lower()
    if any(marker in url_lc for marker in ANTHROPIC.url_markers):
        return ANTHROPIC.key
    return None


def detect_provider_from_har_entry(
    entry: dict[str, object],
    *,
    complete_message: dict[str, object] | None = None,
) -> str | None:
    """Infer provider from HAR entry metadata + request URL + optional response shape.

    // [LAW:one-source-of-truth] HAR provider inference precedence is centralized here:
    // `_cc_dump.provider` > request URL markers > complete response shape.
    """
    metadata = entry.get("_cc_dump", {})
    raw_provider = metadata.get("provider", "") if isinstance(metadata, dict) else ""
    normalized = normalize_provider(str(raw_provider))
    if is_known_provider(normalized):
        return normalized

    request = entry.get("request", {})
    raw_url = request.get("url", "") if isinstance(request, dict) else ""
    provider = provider_from_url_marker(str(raw_url))
    if provider is not None:
        return provider

    return (
        infer_provider_from_complete_message(complete_message)
        if complete_message is not None
        else None
    )


def infer_provider_from_har_entry(
    entry: dict[str, object],
    *,
    complete_message: dict[str, object] | None = None,
) -> str:
    """Infer provider from HAR entry and fall back to default when unknown."""
    return detect_provider_from_har_entry(
        entry,
        complete_message=complete_message,
    ) or DEFAULT_PROVIDER_KEY


def _provider_proxy_env_items(endpoint: ProviderEndpoint) -> tuple[tuple[str, str], ...]:
    if not endpoint.proxy_url:
        return ()
    spec = get_provider_spec(endpoint.provider_key)
    return ((spec.base_url_env, endpoint.proxy_url),)


def infer_provider_from_complete_message(message: dict[str, object]) -> str | None:
    """Best-effort provider inference from complete response shape.

    Returns None when the message shape does not identify the provider family, so
    callers fall back to the default provider.
    """
    # // [LAW:dataflow-not-control-flow] Provider family is derived from response markers.
    # // [LAW:one-source-of-truth] cc-dump is Anthropic-only, so an anthropic message
    # //   identifies the sole provider and every other shape resolves to None.
    if message.get("type") == "message":
        return "anthropic"
    return None


def is_complete_response_for_provider(provider: str, message: dict[str, object]) -> bool:
    """Validate complete-response shape for the provider family.

    // [LAW:dataflow-not-control-flow] One family means one shape check, not a
    //   keyed dispatch. The `provider` argument is vestigial (see get_provider_spec).
    """
    return message.get("type") == "message"
