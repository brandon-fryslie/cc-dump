from cc_dump.tui.side_channel_panel import _render_purpose_usage


def test_render_purpose_usage_empty():
    assert _render_purpose_usage({}) == "Purpose usage: (none)"


def test_render_purpose_usage_shows_token_totals():
    usage = {
        "block_summary": {
            "turns": 2,
            "input_tokens": 10,
            "cache_read_tokens": 20,
            "cache_creation_tokens": 3,
            "output_tokens": 5,
        }
    }
    rendered = _render_purpose_usage(usage)
    assert "Purpose usage:" in rendered
    assert "block_summary" in rendered
    assert "runs=2" in rendered
    assert "in=10" in rendered
    assert "cache_read=20" in rendered
    assert "cache_create=3" in rendered
    assert "out=5" in rendered
