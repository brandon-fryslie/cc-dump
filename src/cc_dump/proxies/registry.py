"""Proxy provider registry and descriptor helpers.

// [LAW:one-source-of-truth] Provider registration + settings descriptors are centralized here.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from collections.abc import Mapping

from cc_dump.proxies.plugin_api import (
    ProxyProviderDescriptor,
    ProxyProviderPlugin,
    ProxySettingDescriptor,
)
from cc_dump.proxies.runtime import PROVIDER_ANTHROPIC


_ANTHROPIC_DESCRIPTOR = ProxyProviderDescriptor(
    provider_id=PROVIDER_ANTHROPIC,
    display_name="Anthropic",
    settings=(
        ProxySettingDescriptor(
            key="proxy_anthropic_base_url",
            label="Anthropic URL",
            description="Base URL when provider=anthropic",
            kind="text",
            default="https://api.anthropic.com",
            env_vars=("ANTHROPIC_BASE_URL",),
        ),
    ),
)

_DESCRIPTORS: dict[str, ProxyProviderDescriptor] = {
    _ANTHROPIC_DESCRIPTOR.provider_id: _ANTHROPIC_DESCRIPTOR,
}
_PLUGINS: dict[str, ProxyProviderPlugin] = {}
_PLUGIN_LOAD_ERRORS: dict[str, str] = {}
_REGISTRY_READY = False
_REGISTRY_LOADING = False


def _discover_plugin_package_names() -> tuple[str, ...]:
    root = Path(__file__).resolve().parent
    # // [LAW:dataflow-not-control-flow] Discovery is deterministic from package layout.
    package_names = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir()
        and not entry.name.startswith("_")
        and (entry / "plugin.py").exists()
    )
    return tuple(package_names)


def _load_plugin_from_package(package_name: str) -> None:
    module_name = f"cc_dump.proxies.{package_name}.plugin"
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        _PLUGIN_LOAD_ERRORS[package_name] = f"import failed: {e}"
        return

    create_plugin = getattr(module, "create_plugin", None)
    if create_plugin is None or not callable(create_plugin):
        _PLUGIN_LOAD_ERRORS[package_name] = (
            "missing required create_plugin() factory"
        )
        return
    try:
        plugin = create_plugin()
        descriptor = plugin.descriptor
    except Exception as e:
        _PLUGIN_LOAD_ERRORS[package_name] = f"factory failed: {e}"
        return
    provider_id = str(descriptor.provider_id or "").strip().lower()
    if not provider_id:
        _PLUGIN_LOAD_ERRORS[package_name] = "invalid empty provider_id"
        return
    if provider_id in _DESCRIPTORS:
        _PLUGIN_LOAD_ERRORS[package_name] = f"duplicate provider_id '{provider_id}'"
        return
    _DESCRIPTORS[provider_id] = descriptor
    _PLUGINS[provider_id] = plugin


def _ensure_registry_loaded() -> None:
    global _REGISTRY_READY, _REGISTRY_LOADING
    if _REGISTRY_READY or _REGISTRY_LOADING:
        return
    _REGISTRY_LOADING = True
    # // [LAW:single-enforcer] Plugin loading/validation is centralized in one registry bootstrap.
    try:
        for package_name in _discover_plugin_package_names():
            _load_plugin_from_package(package_name)
        _REGISTRY_READY = True
    finally:
        _REGISTRY_LOADING = False


def provider_ids() -> tuple[str, ...]:
    _ensure_registry_loaded()
    return tuple(_DESCRIPTORS.keys())


def provider_descriptors() -> tuple[ProxyProviderDescriptor, ...]:
    _ensure_registry_loaded()
    return tuple(_DESCRIPTORS.values())


def provider_descriptor(provider_id: str) -> ProxyProviderDescriptor | None:
    _ensure_registry_loaded()
    return _DESCRIPTORS.get(str(provider_id or "").strip().lower())


def provider_plugin(provider_id: str) -> ProxyProviderPlugin | None:
    _ensure_registry_loaded()
    return _PLUGINS.get(str(provider_id or "").strip().lower())


def all_setting_descriptors() -> tuple[ProxySettingDescriptor, ...]:
    _ensure_registry_loaded()
    output: list[ProxySettingDescriptor] = []
    seen: set[str] = set()
    for descriptor in provider_descriptors():
        for setting in descriptor.settings:
            key = str(setting.key or "").strip()
            if key and key not in seen:
                output.append(setting)
                seen.add(key)
    return tuple(output)


def apply_env_overrides(
    current: Mapping[str, object],
    environ: Mapping[str, str],
) -> dict[str, object]:
    _ensure_registry_loaded()
    # // [LAW:dataflow-not-control-flow] All descriptors are processed through one deterministic override pass.
    updated = dict(current)
    for setting in all_setting_descriptors():
        if not setting.env_vars:
            continue
        for env_var in setting.env_vars:
            if env_var in environ:
                updated[setting.key] = environ[env_var]
                break
    if "CC_DUMP_PROXY_PROVIDER" in environ:
        updated["proxy_provider"] = environ["CC_DUMP_PROXY_PROVIDER"]
    return updated


def plugin_load_errors() -> Mapping[str, str]:
    _ensure_registry_loaded()
    return dict(_PLUGIN_LOAD_ERRORS)
