from pathlib import Path


def test_proxy_pipeline_has_no_provider_specific_imports():
    source = Path("/Users/bmf/code/cc-dump/src/cc_dump/pipeline/proxy.py").read_text()
    assert "cc_dump.proxies.copilot" not in source
    assert "_COPILOT_" not in source
