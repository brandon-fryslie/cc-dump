"""Tests for unified analytics dashboard rendering."""

from cc_dump.tui.panel_renderers import (
    render_analytics_panel,
    render_analytics_summary,
    render_analytics_timeline,
    render_analytics_models,
)


def _snapshot() -> dict:
    return {
        "summary": {
            "turn_count": 3,
            "input_tokens": 1700,
            "output_tokens": 800,
            "cache_read_tokens": 3300,
            "cache_creation_tokens": 10,
            "input_total": 5000,
            "total_tokens": 5800,
            "cache_pct": 66.0,
            "cost_usd": 0.1234,
        },
        "timeline": [
            {
                "sequence_num": 1,
                "model": "claude-sonnet-4",
                "input_total": 1000,
                "output_tokens": 200,
                "cache_pct": 20.0,
                "delta_input": 0,
            },
            {
                "sequence_num": 2,
                "model": "claude-haiku-4",
                "input_total": 1200,
                "output_tokens": 300,
                "cache_pct": 40.0,
                "delta_input": 200,
            },
        ],
        "models": [
            {
                "model_label": "Sonnet 4",
                "turns": 2,
                "input_total": 3200,
                "output_tokens": 500,
                "cache_pct": 62.0,
                "cost_usd": 0.091,
            },
            {
                "model_label": "Haiku 4",
                "turns": 1,
                "input_total": 1800,
                "output_tokens": 300,
                "cache_pct": 72.0,
                "cost_usd": 0.032,
            },
        ],
    }


def test_render_analytics_summary():
    text = render_analytics_summary(_snapshot())
    assert "Analytics:" in text
    assert "SUMMARY" in text
    assert "Turns: 3" in text
    assert "Cache: 66%" in text


def test_render_analytics_timeline():
    text = render_analytics_timeline(_snapshot())
    assert "TIMELINE" in text
    assert "Turn" in text
    assert "+200" in text


def test_render_analytics_models():
    text = render_analytics_models(_snapshot())
    assert "MODELS" in text
    assert "Sonnet 4" in text
    assert "$0.091" in text


def test_render_analytics_panel_dispatch():
    snapshot = _snapshot()
    assert "SUMMARY" in render_analytics_panel(snapshot, "summary")
    assert "TIMELINE" in render_analytics_panel(snapshot, "timeline")
    assert "MODELS" in render_analytics_panel(snapshot, "models")
    assert "SUMMARY" in render_analytics_panel(snapshot, "unknown")
