"""Standard proxy-plugin contract for provider-specific behavior.

// [LAW:one-source-of-truth] Provider capabilities and settings descriptors are defined here.
// [LAW:locality-or-seam] Core proxy code talks only to this contract, never provider internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from cc_dump.proxies.runtime import ProxyRuntimeSnapshot


SettingKind = Literal["text", "bool", "select"]


@dataclass(frozen=True)
class ProxySettingDescriptor:
    key: str
    label: str
    description: str
    kind: SettingKind
    default: object
    options: tuple[str, ...] = ()
    secret: bool = False
    env_vars: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProxyProviderDescriptor:
    provider_id: str
    display_name: str
    settings: tuple[ProxySettingDescriptor, ...]


@dataclass(frozen=True)
class ProxyAuthResult:
    settings_updates: Mapping[str, object]
    message: str


@dataclass(frozen=True)
class ProxyRequestContext:
    request_id: str
    request_path: str
    request_body: dict | None
    method: str
    request_headers: Mapping[str, str]
    runtime_snapshot: ProxyRuntimeSnapshot
    handler: Any
    event_queue: Any
    safe_headers: Any


class ProxyProviderPlugin(Protocol):
    @property
    def descriptor(self) -> ProxyProviderDescriptor:
        ...

    def handles_path(self, request_path: str) -> bool:
        ...

    def expects_json_body(self, request_path: str) -> bool:
        ...

    def handle_request(self, context: ProxyRequestContext) -> bool:
        ...


class ProxyAuthCapablePlugin(Protocol):
    def run_auth_flow(self, *, force: bool) -> ProxyAuthResult:
        ...
