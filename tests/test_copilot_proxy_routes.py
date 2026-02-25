import cc_dump.proxies.registry


def _copilot_plugin():
    plugin = cc_dump.proxies.registry.provider_plugin("copilot")
    assert plugin is not None
    return plugin


def test_copilot_supported_paths_include_openai_aliases():
    plugin = _copilot_plugin()
    assert plugin.handles_path("/v1/messages")
    assert plugin.handles_path("/v1/messages/count_tokens")
    assert plugin.handles_path("/v1/models")
    assert plugin.handles_path("/models")
    assert plugin.handles_path("/v1/chat/completions")
    assert plugin.handles_path("/chat/completions")
    assert plugin.handles_path("/v1/embeddings")
    assert plugin.handles_path("/embeddings")
    assert plugin.handles_path("/usage")
    assert plugin.handles_path("/v1/usage")
    assert plugin.handles_path("/token")
    assert plugin.handles_path("/v1/token")
    assert not plugin.handles_path("/v1/unknown")


def test_json_body_expectations_include_alias_paths():
    plugin = _copilot_plugin()
    assert plugin.expects_json_body("/v1/messages")
    assert plugin.expects_json_body("/v1/messages/count_tokens")
    assert plugin.expects_json_body("/v1/chat/completions")
    assert plugin.expects_json_body("/chat/completions")
    assert plugin.expects_json_body("/v1/embeddings")
    assert plugin.expects_json_body("/embeddings")
    assert not plugin.expects_json_body("/models")
    assert not plugin.expects_json_body("/usage")
    assert not plugin.expects_json_body("/v1/usage")
    assert not plugin.expects_json_body("/token")
    assert not plugin.expects_json_body("/v1/token")
