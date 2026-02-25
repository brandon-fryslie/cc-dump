"""Runtime-switchable upstream proxy configuration.

// [LAW:one-source-of-truth] Runtime keeps one canonical provider + settings snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Mapping


PROVIDER_ANTHROPIC = "anthropic"


def _normalize_provider(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return PROVIDER_ANTHROPIC
    return raw


def _normalize_url(value: object) -> str:
    return str(value or "").strip().rstrip("/")


def _normalize_rate_limit_seconds(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, parsed)


def _normalize_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_value(key: str, value: object) -> object:
    # // [LAW:dataflow-not-control-flow] One deterministic normalization pipeline for all settings.
    if key.endswith("_base_url"):
        return _normalize_url(value)
    if key.endswith("_rate_limit_seconds"):
        return _normalize_rate_limit_seconds(value)
    if key.endswith("_rate_limit_wait"):
        return _normalize_bool(value, default=False)
    return value


@dataclass(frozen=True)
class ProxyRuntimeSnapshot:
    provider: str
    settings: Mapping[str, object]

    def get(self, key: str, default: object = None) -> object:
        return self.settings.get(key, default)

    def get_text(self, key: str, default: str = "") -> str:
        value = self.settings.get(key, default)
        return str(value if value is not None else default).strip()

    def get_bool(self, key: str, default: bool = False) -> bool:
        return _normalize_bool(self.settings.get(key), default=default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            parsed = int(self.settings.get(key, default))
        except (TypeError, ValueError):
            parsed = default
        return parsed

    @property
    def active_base_url(self) -> str:
        if self.provider == PROVIDER_ANTHROPIC:
            return self.get_text("proxy_anthropic_base_url")
        provider_key = f"proxy_{self.provider}_base_url"
        provider_url = self.get_text(provider_key)
        if provider_url:
            return provider_url
        return self.get_text("proxy_anthropic_base_url")

    @property
    def reverse_proxy_enabled(self) -> bool:
        return bool(self.active_base_url)


class ProxyRuntime:
    """Thread-safe mutable store for active proxy provider + settings."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = ProxyRuntimeSnapshot(
            provider=PROVIDER_ANTHROPIC,
            settings={},
        )

    def update_from_settings(self, settings: Mapping[str, object]) -> ProxyRuntimeSnapshot:
        normalized = {
            str(key): _normalize_value(str(key), value)
            for key, value in dict(settings).items()
        }
        snapshot = ProxyRuntimeSnapshot(
            provider=_normalize_provider(normalized.get("proxy_provider")),
            settings=normalized,
        )
        with self._lock:
            self._snapshot = snapshot
            return self._snapshot

    def snapshot(self) -> ProxyRuntimeSnapshot:
        with self._lock:
            return self._snapshot
