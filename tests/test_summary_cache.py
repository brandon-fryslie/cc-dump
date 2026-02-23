from cc_dump.ai.summary_cache import SummaryCache


def test_cache_key_includes_purpose_and_prompt_version(tmp_path):
    cache = SummaryCache(path=tmp_path / "summary-cache.json")
    content = "same content"
    key_a = cache.make_key(
        purpose="block_summary",
        prompt_version="v1",
        content=content,
    )
    key_b = cache.make_key(
        purpose="block_summary",
        prompt_version="v2",
        content=content,
    )
    key_c = cache.make_key(
        purpose="decision_ledger",
        prompt_version="v1",
        content=content,
    )
    assert key_a != key_b
    assert key_a != key_c
    assert key_b != key_c


def test_cache_persists_and_loads_entries(tmp_path):
    path = tmp_path / "summary-cache.json"
    cache = SummaryCache(path=path)
    key = cache.make_key(
        purpose="block_summary",
        prompt_version="v1",
        content="hello",
    )
    cache.put(
        key=key,
        purpose="block_summary",
        prompt_version="v1",
        content="hello",
        summary_text="cached summary",
    )

    reloaded = SummaryCache(path=path)
    entry = reloaded.get(key)
    assert entry is not None
    assert entry.summary_text == "cached summary"
