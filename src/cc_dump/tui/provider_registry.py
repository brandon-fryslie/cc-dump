"""Provider registry — single source of truth for provider-keyed state.

// [LAW:single-enforcer] Provider state, endpoint, and per-provider session
//   tracking all live on one Provider record.
// [LAW:one-source-of-truth] No parallel dicts; one Provider per key.
// [LAW:dataflow-not-control-flow] Registry returns Providers; callers never
//   branch on "which dict owns this piece?".

This module is RELOADABLE. Stable boundary modules import it as a module object.
"""

from __future__ import annotations

from dataclasses import dataclass

import cc_dump.providers
import cc_dump.core.formatting_impl


@dataclass
class Provider:
    """A single upstream provider and everything it owns.

    Constructed exclusively by ProviderRegistry at the app boundary.
    `is_default` and `key` are decided at construction and never re-derived.
    """

    key: str
    runtime_state: "cc_dump.core.formatting_impl.ProviderRuntimeState"
    endpoint: "cc_dump.providers.ProviderEndpoint"
    is_default: bool
    last_notified_session: str | None = None


class ProviderRegistry:
    """Owns all providers. Constructed once at app boundary.

    // [LAW:single-enforcer] All provider construction funnels through here.
    // [LAW:dataflow-not-control-flow] get() raises on unknown keys — the
    //   boundary already validated every provider at construction time, so
    //   downstream code never needs a "what if unknown provider?" branch.
    """

    def __init__(self, providers: dict[str, Provider]) -> None:
        if cc_dump.providers.DEFAULT_PROVIDER_KEY not in providers:
            raise ValueError(
                f"ProviderRegistry requires a default provider "
                f"({cc_dump.providers.DEFAULT_PROVIDER_KEY!r})"
            )
        self._providers = dict(providers)
        self._default = self._providers[cc_dump.providers.DEFAULT_PROVIDER_KEY]

    def default(self) -> Provider:
        return self._default

    def get(self, key: str) -> Provider:
        return self._providers[key]

    def all(self) -> tuple[Provider, ...]:
        return tuple(self._providers.values())

    def total_request_count(self) -> int:
        return sum(p.runtime_state.request_counter for p in self._providers.values())


def build_registry(
    *,
    provider_states: dict[str, "cc_dump.core.formatting_impl.ProviderRuntimeState"] | None,
    default_state: "cc_dump.core.formatting_impl.ProviderRuntimeState",
    provider_endpoints: "cc_dump.providers.ProviderEndpointMap | None",
    host: str,
    port: int,
    target: str | None,
) -> ProviderRegistry:
    """Single enforcer: raw constructor inputs → ProviderRegistry.

    // [LAW:single-enforcer] The one place raw provider_states/provider_endpoints
    //   are normalized into Provider records.
    """
    states = dict(provider_states or {})
    states.setdefault(cc_dump.providers.DEFAULT_PROVIDER_KEY, default_state)

    endpoints = dict(provider_endpoints) if provider_endpoints else {
        cc_dump.providers.DEFAULT_PROVIDER_KEY: cc_dump.providers.default_provider_endpoint(
            host, port, target or ""
        )
    }

    providers: dict[str, Provider] = {}
    # // [LAW:dataflow-not-control-flow] Every state key gets a Provider;
    # every endpoint must name a state that exists.
    for key, state in states.items():
        endpoint = endpoints.get(key)
        if endpoint is None:
            raise ValueError(
                f"Provider {key!r} has runtime state but no endpoint"
            )
        providers[key] = Provider(
            key=key,
            runtime_state=state,
            endpoint=endpoint,
            is_default=(key == cc_dump.providers.DEFAULT_PROVIDER_KEY),
        )
    return ProviderRegistry(providers)
