from pathlib import Path

import cc_dump.app.settings_store
import cc_dump.proxies.registry


def test_registry_exposes_provider_descriptors():
    provider_ids = cc_dump.proxies.registry.provider_ids()
    assert "anthropic" in provider_ids
    assert "copilot" in provider_ids


def test_copilot_plugin_conforms_to_contract_shape():
    plugin = cc_dump.proxies.registry.provider_plugin("copilot")
    assert plugin is not None
    assert hasattr(plugin, "descriptor")
    assert hasattr(plugin, "handles_path")
    assert hasattr(plugin, "expects_json_body")
    assert hasattr(plugin, "handle_request")


def test_registry_settings_are_reflected_in_settings_schema():
    descriptor_keys = {
        descriptor.key
        for descriptor in cc_dump.proxies.registry.all_setting_descriptors()
    }
    assert descriptor_keys
    for key in descriptor_keys:
        assert key in cc_dump.app.settings_store.SCHEMA


def test_registry_applies_env_overrides_from_descriptors():
    overrides = cc_dump.proxies.registry.apply_env_overrides(
        {"proxy_provider": "anthropic"},
        {
            "CC_DUMP_PROXY_PROVIDER": "copilot",
            "CC_DUMP_COPILOT_BASE_URL": "https://copilot.example.com",
        },
    )
    assert overrides["proxy_provider"] == "copilot"
    assert overrides["proxy_copilot_base_url"] == "https://copilot.example.com"


def test_registry_uses_generic_plugin_discovery_without_provider_imports():
    source = Path("/Users/bmf/code/cc-dump/src/cc_dump/proxies/registry.py").read_text()
    assert "cc_dump.proxies.copilot" not in source
    assert "create_plugin()" in source


def test_registry_exposes_plugin_load_errors_mapping():
    errors = cc_dump.proxies.registry.plugin_load_errors()
    assert isinstance(errors, dict)
