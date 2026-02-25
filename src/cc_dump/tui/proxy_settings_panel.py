"""Proxy settings panel (provider + provider-specific descriptors).

This module is RELOADABLE.
"""

from __future__ import annotations

import cc_dump.app.settings_store
import cc_dump.proxies.registry
from cc_dump.tui.settings_form_panel import FieldDef, SettingsFormPanel


def _provider_setting_fields() -> list[FieldDef]:
    fields: list[FieldDef] = []
    for descriptor in cc_dump.proxies.registry.all_setting_descriptors():
        if descriptor.kind == "bool":
            default_value: str | bool = bool(descriptor.default)
        else:
            default_value = str(descriptor.default)
        fields.append(
            FieldDef(
                key=descriptor.key,
                label=descriptor.label,
                description=descriptor.description,
                kind=descriptor.kind,
                default=default_value,
                options=tuple(descriptor.options),
                secret=bool(descriptor.secret),
            )
        )
    return fields


def build_proxy_settings_fields() -> list[FieldDef]:
    provider_options = tuple(
        descriptor.provider_id
        for descriptor in cc_dump.proxies.registry.provider_descriptors()
    )
    # // [LAW:one-source-of-truth] Proxy field list derives from provider descriptors only.
    return [
        FieldDef(
            key="proxy_provider",
            label="Proxy Provider",
            description="Active upstream adapter (switches live)",
            kind="select",
            options=provider_options,
            default=str(cc_dump.app.settings_store.SCHEMA["proxy_provider"]),
        ),
        *_provider_setting_fields(),
    ]


PROXY_SETTINGS_FIELDS: tuple[FieldDef, ...] = tuple(build_proxy_settings_fields())


class ProxySettingsPanel(SettingsFormPanel):
    def __init__(self, initial_values: dict | None = None) -> None:
        super().__init__(
            panel_key="proxy_settings",
            title="Proxy Settings",
            fields=PROXY_SETTINGS_FIELDS,
            initial_values=initial_values,
        )


def create_proxy_settings_panel(initial_values: dict | None = None) -> ProxySettingsPanel:
    return ProxySettingsPanel(initial_values=initial_values)
