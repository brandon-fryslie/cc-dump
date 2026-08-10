"""Provider registry — single source of truth for the provider's runtime state.

cc-dump is Anthropic-only, so the "registry" owns exactly one Provider.

// [LAW:no-mode-explosion] One provider means no keyed dict: the registry holds
//   the single Provider and returns it for any key. The map-keyed constructor
//   inputs collapsed to a single runtime state plus the endpoint coordinates.
// [LAW:single-enforcer] Provider state, endpoint, and per-provider session
//   tracking all live on the one Provider record.

This module is RELOADABLE. Stable boundary modules import it as a module object.
"""

from __future__ import annotations

from dataclasses import dataclass

import cc_dump.core.formatting_impl
import cc_dump.providers


@dataclass
class Provider:
    """The upstream provider and everything it owns.

    Constructed exclusively by build_registry at the app boundary.
    """

    key: str
    runtime_state: cc_dump.core.formatting_impl.ProviderRuntimeState
    endpoint: cc_dump.providers.ProviderEndpoint
    is_default: bool
    last_notified_session: str | None = None


class ProviderRegistry:
    """Owns the single provider. Constructed once at the app boundary.

    // [LAW:dataflow-not-control-flow] get() ignores the key and returns the sole
    //   Provider — downstream code never branches on "which provider?".
    """

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    def default(self) -> Provider:
        return self._provider

    def get(self, key: str) -> Provider:
        return self._provider

    def all(self) -> tuple[Provider, ...]:
        return (self._provider,)

    def endpoints(self) -> dict[str, object]:
        """// [LAW:one-source-of-truth] Canonical key→endpoint projection."""
        return {self._provider.key: self._provider.endpoint}

    def total_request_count(self) -> int:
        return self._provider.runtime_state.request_counter


def build_registry(
    *,
    default_state: cc_dump.core.formatting_impl.ProviderRuntimeState,
    host: str,
    port: int,
    target: str | None,
) -> ProviderRegistry:
    """Build the single-provider registry at the app boundary.

    // [LAW:single-enforcer] The one place the runtime state + endpoint are
    //   normalized into the Provider record.
    """
    endpoint = cc_dump.providers.default_provider_endpoint(host, port, target or "")
    provider = Provider(
        key=cc_dump.providers.DEFAULT_PROVIDER_KEY,
        runtime_state=default_state,
        endpoint=endpoint,
        is_default=True,
    )
    return ProviderRegistry(provider)
